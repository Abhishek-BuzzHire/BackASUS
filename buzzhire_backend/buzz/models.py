from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .managers import UserManager

class User(AbstractBaseUser, PermissionsMixin): # <-- Inherit from AbstractBaseUser and PermissionsMixin
    id = models.AutoField(primary_key=True)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    
    # Required fields for AbstractBaseUser compatibility
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True) # Essential for login
    is_superuser = models.BooleanField(default=False) # Inherited from PermissionsMixin

    # Your custom fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    lastlogin = models.DateTimeField(null=True, blank=True)

    # Class attributes required by Django's auth system
    USERNAME_FIELD = 'email'  # <-- The field used for login (e.g., in Simple JWT)
    REQUIRED_FIELDS = ['name'] # <-- Fields required when creating a user via command line
    
    objects = UserManager() # <-- Assign the custom manager

    def __str__(self):
        return self.email

# ===========================
# ATTENDANCE MODEL
# ===========================

class Attendance(models.Model):
    BRANCH_CHOICES = (
        ("NOIDA", "Noida"),
        ("SAKET", "Saket"),
    )

    WORK_STATUS_CHOICES = (
        ("WFO", "Work From Office"),
        ("WFH", "Work From Home"),
        ("ABSENT", "Absent"),
        ("NO MENTION", "no mention"),
        ("LEAVE", "Leave"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    date = models.DateField()
    
    punch_in_time = models.DateTimeField(null=True, blank=True)
    punch_out_time = models.DateTimeField(null=True, blank=True)

    punch_in_lat = models.FloatField(null=True, blank=True)
    punch_in_lon = models.FloatField(null=True, blank=True)

    punch_out_lat = models.FloatField(null=True, blank=True)
    punch_out_lon = models.FloatField(null=True, blank=True)

    branch_name = models.CharField(
        max_length=20,
        choices=BRANCH_CHOICES,
        null=True,
        blank=True
    )

    work_status = models.CharField(
        max_length=20,
        choices=WORK_STATUS_CHOICES,
        default="NO MENTION"
    )




def save(self, *args, **kwargs):

    # 1️⃣ Agar admin ne WFH set kiya hai → touch mat karo
    if self.work_status == "WFH":
        super().save(*args, **kwargs)
        return

    # 2️⃣ Punch-in hua hai → Present (WFO)
    if self.punch_in_time:
        self.work_status = "WFO"

    # 3️⃣ Punch-in + Punch-out dono hue → Final WFO
    if self.punch_in_time and self.punch_out_time:
        self.work_status = "WFO"

    # 4️⃣ Kuch bhi nahi hua → ABSENT (default)
    super().save(*args, **kwargs)


    class Meta:
        unique_together = ("user", "date")   # 🔥 duplicate attendance रोकता है
        indexes = [
            models.Index(fields=["user", "date"]),
        ]

    def __str__(self):
        return f"{self.user.email} | {self.date} | {self.work_status}"




# ===========================
# WFH REQUEST MODEL
# ===========================
class WFHRequest(models.Model):

    STATUS_CHOICES = (
        ("IN_PROGRESS", "In Progress"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # 👉 jis date ke liye WFH chahiye
    date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="IN_PROGRESS"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "date")   # 🔥 same date pe 2 WFH request nahi

    def __str__(self):
        return f"{self.user.email} | {self.date} | {self.status}"
    
 