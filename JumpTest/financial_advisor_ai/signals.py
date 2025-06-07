from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile
from social_django.models import UserSocialAuth


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create a UserProfile when a new User is created"""
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=UserSocialAuth)
def save_google_token(sender, instance, created, **kwargs):
    """Save Google tokens to UserProfile when a user connects via Google OAuth"""
    if instance.provider == 'google-oauth2':
        try:
            # Get or create user profile
            profile, created = UserProfile.objects.get_or_create(
                user=instance.user)

            # Save tokens
            extra_data = instance.extra_data
            profile.google_token = extra_data.get('access_token', '')
            profile.google_refresh_token = extra_data.get('refresh_token', '')
            profile.save()
        except Exception as e:
            print(f"Error saving Google tokens: {e}")
