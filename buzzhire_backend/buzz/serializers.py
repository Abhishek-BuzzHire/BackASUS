from rest_framework import serializers

from .models import Attendance, User, WFHRequest, LeaveRequest, EmployeeLeaveBucket, RoleChoices, CompanyWorkingRules, CompanyHoliday, HolidayOverride
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        # Call the base method to get the token object (includes user_id, email)
        token = super().get_token(user)

        # Add custom claims
        token['name'] = user.name # <-- Add the name
        token['email'] = user.email # <-- Add the email (if not added by default)
        token["username"] = user.username
        token['picture'] = user.picture

        return token


# =====================================================
# EMPLOYEE SELF PROFILE
# =====================================================
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = "__all__"

    def validate_role(self, value):
        if not RoleChoices.objects.filter(code=value, is_active=True).exists():
            raise serializers.ValidationError("Invalid role selected")
        return value



# =====================================================
# ATTENDANCE SERIALIZER
# =====================================================

# class AttendanceSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Attendance
#         fields = "__all__"




class AttendanceSerializer(serializers.ModelSerializer):
    punch_in_time = serializers.DateTimeField(read_only=True)
    punch_out_time = serializers.DateTimeField(read_only=True)

    date = serializers.DateField(read_only=True)  # <-- Must be read_only


    class Meta:
        model = Attendance
        fields = "__all__"


class WFHRequestSerializer(serializers.ModelSerializer): 
    # readable fields (response only)
    user_name = serializers.CharField(source="user.name", read_only=True)
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = WFHRequest
        fields = [
            "id",
            "user",          # POST ke time user_id
            "user_name",     # response ke time
            "user_email",    # response ke time
            "date",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "status",
            "created_at",
            "updated_at",
        ]


class ApplyLeaveSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveRequest
        fields = ["user_id", "start_date", "end_date", "reason", ]

    def validate(self, data):
        if data["start_date"] > data["end_date"]:
            raise serializers.ValidationError(
                "Start date cannot be after end date"
            )
        return data



# =====================================================
# ✅ EMPLOYEE LEAVE BUCKET SERIALIZER (NEW)
# =====================================================
class EmployeeLeaveBucketSerializer(serializers.ModelSerializer):
    """
    SOURCE OF TRUTH for leave balance
    """

    class Meta:
        model = EmployeeLeaveBucket
        fields = [
            "total_leave",
            "taken_leave",
            "remaining_leave",
            "created_at",
        ]
       

class RoleChoicesSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleChoices
        fields = ["id", "code", "label"]



class CompanyWorkingRulesSerializer(serializers.ModelSerializer):

    class Meta:
        model = CompanyWorkingRules
        fields = [
            "id",
            "company_name",
            "working_days",
            "daily_work_hours",
            "weekly_work_hours",
            "monthly_work_hours",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def validate_working_days(self, value):
        allowed = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}

        if not isinstance(value, list):
            raise serializers.ValidationError("working_days must be a list")

        invalid = set(value) - allowed
        if invalid:
            raise serializers.ValidationError(
                f"Invalid weekdays: {', '.join(invalid)}"
            )

        return value
    


class CompanyHolidaySerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.name", read_only=True
    )

    class Meta:
        model = CompanyHoliday
        fields = [
            "id",
            "name",
            "date",
            "holiday_type",
            "is_active",
            "created_by",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["created_at", "created_by_name"]

    def validate(self, data):
        date = data.get("date")
        name = data.get("name")

        qs = CompanyHoliday.objects.filter(date=date, name=name)
        if self.instance:
            qs = qs.exclude(id=self.instance.id)

        if qs.exists():
            raise serializers.ValidationError(
                "Holiday with this name and date already exists"
            )

        return data
    


class HolidayOverrideSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.name", read_only=True
    )

    class Meta:
        model = HolidayOverride
        fields = [
            "id",
            "date",
            "override_type",
            "reason",
            "created_by",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = ["created_at", "created_by_name"]

    def validate(self, data):
        date = data.get("date")
        override_type = data.get("override_type")

        qs = HolidayOverride.objects.filter(
            date=date,
            override_type=override_type
        )

        if self.instance:
            qs = qs.exclude(id=self.instance.id)

        if qs.exists():
            raise serializers.ValidationError(
                "This override already exists for this date"
            )

        return data
    
class CalendarHolidaySerializer(serializers.ModelSerializer):

    class Meta:
        model = CompanyHoliday
        fields = [
            "id",
            "name",
            "date",
            "holiday_type",
            "is_active",
        ]


class CalendarOverrideSerializer(serializers.ModelSerializer):

    class Meta:
        model = HolidayOverride
        fields = [
            "id",
            "date",
            "override_type",
            "reason",
        ]