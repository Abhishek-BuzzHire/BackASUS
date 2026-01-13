from django.contrib.auth.base_user import BaseUserManager

class UserManager(BaseUserManager):
    """
    Custom user model manager where email is the unique identifier
    for authentication instead of usernames.
    """
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError("Username is required")

        if not email:
            raise ValueError(('The Email must be set'))
        
        email = self.normalize_email(email)
        user = self.model(username=email ,email=email, **extra_fields)
        user.set_password(password)
        user.save()

        from buzz.models import EmployeeLeaveBucket
        
        EmployeeLeaveBucket.objects.get_or_create(
        user=user,
        defaults={
            "total_leave": 18,
            "taken_leave": 0,
            "remaining_leave": 18
        }
    )


        return user
    
    

    def create_superuser(self, username, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(('Superuser must have is_superuser=True.'))
            
        # The fields 'name' and 'lastlogin' will be handled by the **extra_fields
        return self.create_user(username ,email, password, **extra_fields)