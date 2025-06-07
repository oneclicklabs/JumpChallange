
import os
import numpy as np
from typing import List, Dict, Any, Optional
from langchain_community.embeddings import OpenAIEmbeddings
# from langchain.embeddings import OpenAIEmbeddings
# from langchain.vectorstores import FAISS
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.schema import Document
from langchain.chains import ConversationalRetrievalChain
from langchain.llms import OpenAI
from langchain_community.llms import OpenAI
from datetime import datetime


class RAGService:
    def __init__(self, api_key: str):
        os.environ["OPENAI_API_KEY"] = api_key
        self.embeddings = OpenAIEmbeddings()
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        self.email_vector_store = None
        self.hubspot_vector_store = None
        self.combined_vector_store = None
        self.llm = OpenAI(temperature=0)

    def process_emails(self, emails: List[Dict[str, Any]]):
        """Process emails and create vector store for them"""
        documents = []
        for email in emails:
            content = f"Subject: {email.get('subject', 'No Subject')}\n"
            content += f"Date: {email.get('date_str', '')}\n"
            content += f"From: {email.get('from', '')}\n"
            content += f"Snippet: {email.get('snippet', '')}\n"

            doc = Document(
                page_content=content,
                metadata={
                    "source": "email",
                    "subject": email.get('subject', ''),
                    "from": email.get('from', ''),
                    "date": email.get('date_str', ''),
                    "email_id": email.get('id', '')
                }
            )
            documents.append(doc)

        docs = self.text_splitter.split_documents(documents)
        self.email_vector_store = FAISS.from_documents(docs, self.embeddings)

        # Combine if hubspot data exists
        if self.hubspot_vector_store:
            self._combine_vector_stores()

    def process_hubspot_data(self, contacts: List[Dict[str, Any]], notes: List[Dict[str, Any]]):
        """Process HubSpot contacts and notes and create vector store for them"""
        documents = []

        # Process contacts
        for contact in contacts:
            content = f"Contact: {contact.get('name', '')}\n"
            content += f"Email: {contact.get('email', '')}\n"
            content += f"Last interaction: {contact.get('last_interaction', '')}\n"

            doc = Document(
                page_content=content,
                metadata={
                    "source": "hubspot_contact",
                    "contact_id": contact.get('id', ''),
                    "name": contact.get('name', ''),
                    "email": contact.get('email', '')
                }
            )
            documents.append(doc)

        # Process notes
        for note in notes:
            content = f"Contact: {note.get('contact_name', '')}\n"
            content += f"Note: {note.get('content', '')}\n"
            content += f"Date: {note.get('date', '')}\n"

            doc = Document(
                page_content=content,
                metadata={
                    "source": "hubspot_note",
                    "contact_id": note.get('contact_id', ''),
                    "contact_name": note.get('contact_name', ''),
                    "date": note.get('date', '')
                }
            )
            documents.append(doc)

        docs = self.text_splitter.split_documents(documents)
        self.hubspot_vector_store = FAISS.from_documents(docs, self.embeddings)

        # Combine if email data exists
        if self.email_vector_store:
            self._combine_vector_stores()

    def _combine_vector_stores(self):
        """Combine email and hubspot vector stores"""
        if self.email_vector_store and self.hubspot_vector_store:
            # Combine both vector stores
            email_docs = self.email_vector_store.similarity_search(
                "", k=100000)
            hubspot_docs = self.hubspot_vector_store.similarity_search(
                "", k=100000)
            combined_docs = email_docs + hubspot_docs
            self.combined_vector_store = FAISS.from_documents(
                combined_docs, self.embeddings)

    def retrieve_related_contacts(self, name_query: str) -> List[Dict[str, Any]]:
        """Retrieve contacts that match a partial name"""
        if not self.combined_vector_store and not self.hubspot_vector_store:
            return []

        vector_store = self.combined_vector_store or self.hubspot_vector_store
        results = vector_store.similarity_search(
            f"contact name {name_query}", k=5)

        contacts = []
        for doc in results:
            if doc.metadata.get("source") in ["hubspot_contact", "hubspot_note"]:
                contact_id = doc.metadata.get("contact_id")
                contact_name = doc.metadata.get(
                    "name") or doc.metadata.get("contact_name")
                contact_email = doc.metadata.get("email", "")

                if contact_id and contact_name:
                    contact = {
                        "id": contact_id,
                        "name": contact_name,
                        "email": contact_email
                    }

                    # Only add if not already in list
                    if not any(c.get("id") == contact_id for c in contacts):
                        contacts.append(contact)

        return contacts

    def answer_question(self, question: str, chat_history: List[Dict[str, str]], contact_id: Optional[str] = None) -> str:
        """Answer a question using the combined vector store"""
        if not self.combined_vector_store:
            if not self.email_vector_store and not self.hubspot_vector_store:
                return "I don't have enough data to answer your question. Please sync your Gmail and HubSpot data first."

            # Use whatever we have
            vector_store = self.email_vector_store or self.hubspot_vector_store
        else:
            vector_store = self.combined_vector_store

        # Filter by contact_id if provided
        if contact_id:
            # We can filter the retriever to only return documents related to this contact
            def filter_by_contact(doc):
                meta = doc.metadata
                return (meta.get("contact_id") == contact_id or
                        meta.get("email") == contact_id or
                        contact_id in meta.get("from", ""))

            retriever = vector_store.as_retriever(
                search_kwargs={"filter": filter_by_contact})
        else:
            retriever = vector_store.as_retriever(search_kwargs={"k": 5})

        # Format chat history for LangChain
        formatted_history = []
        for chat in chat_history:
            if chat.get("role") == "user" and chat.get("content"):
                formatted_history.append((chat["content"], ""))

        # Create conversation chain
        qa_chain = ConversationalRetrievalChain.from_llm(
            llm=self.llm,
            retriever=retriever,
            return_source_documents=True
        )

        # Get answer
        result = qa_chain(
            {"question": question, "chat_history": formatted_history})

        return result["answer"]


def extract_potential_names(text):
    """Extract potential person names from a text"""
    # This could be enhanced with NLP libraries like spaCy
    # but for simplicity, I'm using regex patterns
    import re

    # Look for capitalized words that might be names
    potential_names = re.findall(r'\b([A-Z][a-z]+)\b', text)
    return potential_names


def score_name_match(name, query):
    """Score how well a contact name matches a query"""
    name_lower = name.lower()
    query_lower = query.lower()

    # Exact match
    if query_lower in name_lower.split():
        return 1.0

    # Partial match
    if query_lower in name_lower:
        return 0.7

    # Initial match (e.g. "JD" matches "John Doe")
    initials = ''.join([n[0].lower() for n in name_lower.split() if n])
    if query_lower == initials:
        return 0.9

    return 0.0
