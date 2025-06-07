class GoogleOAuthFixMiddleware:
    """
    Middleware to fix URLs from Google OAuth that contain spaces and extra parameters.
    This middleware will handle URLs like:
    /oauth/complete/google-oauth2/ flowName=GeneralOAuthFlow
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Fix paths that have spaces in them (which shouldn't happen but Google does it)
        if ' ' in request.path and 'oauth/complete/google-oauth2/' in request.path:
            # Extract the code parameter which is what we need
            code = request.GET.get('flowName', '')
            if code:
                # Redirect to the proper URL with just the code
                from django.shortcuts import redirect
                clean_url = f'/oauth/complete/google-oauth2/?flowName={code}'
                return redirect(clean_url)

        # Continue with normal request processing
        response = self.get_response(request)
        return response
