from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from .managers import UserManager
import uuid

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
        ("LEAVE", "Leave"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    
    date = models.DateField(null=True, blank=True)
    
    punch_in_time = models.DateTimeField(null=True, blank=True)
    punch_out_time = models.DateTimeField(null=True, blank=True)

    punch_in_lat = models.FloatField(null=True, blank=True)
    punch_in_lon = models.FloatField(null=True, blank=True)

    punch_out_lat = models.FloatField(null=True, blank=True)
    punch_out_lon = models.FloatField(null=True, blank=True)

    branch_name = models.CharField(max_length=100, choices=BRANCH_CHOICES, null=True, blank=True)
    work_status = models.CharField(max_length=20, choices=WORK_STATUS_CHOICES, null=True, blank=True)

    class Meta:
        unique_together = ("user", "date")


    def __str__(self):
        return f"{self.user.email} | {self.punch_in_time}"


class WFHRequest(models.Model):

    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # 👉 jis date ke liye WFH chahiye
    date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "date")   # 🔥 same date pe 2 WFH request nahi

    def __str__(self):
        return f"{self.user.email} | {self.date} | {self.status}"
    



class AttendanceCorrectionRequest(models.Model):
    REQUEST_TYPE_CHOICES = (
        ("PUNCH_IN", "Punch In"),
        ("PUNCH_OUT", "Punch Out"),
    )

    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE,
        related_name="attendance_corrections"
    )

    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name="correction_requests"
    )

    request_type = models.CharField(
        max_length=10,
        choices=REQUEST_TYPE_CHOICES
    )

    requested_time = models.DateTimeField()
    reason = models.TextField()

    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="PENDING"
    )

    approval_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    admin_comment = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} | {self.request_type} | {self.status}"


class LeaveRequest(models.Model):
    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("CANCELLED", "Cancelled"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="leave_request")

    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.PositiveIntegerField()
    reason = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"User {self.user} | {self.start_date} - {self.end_date}"    




class EmployeeLeaveBucket(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="leave_bucket"
    )
    total_leave = models.IntegerField(default=18)
    remaining_leave = models.IntegerField(default=18)
    taken_leave = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} - Remaining: {self.remaining_leave}"
