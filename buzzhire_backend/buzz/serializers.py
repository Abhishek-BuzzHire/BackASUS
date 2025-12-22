from rest_framework import serializers

from .models import Attendance, User, WFHRequest
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from django.utils import timezone

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        # Call the base method to get the token object (includes user_id, email)
        token = super().get_token(user)

        # Add custom claims
        token['name'] = user.name # <-- Add the name
        token['email'] = user.email # <-- Add the email (if not added by default)
        token['picture'] = user.picture

        return token


# =====================================================
# EMPLOYEE SELF PROFILE
# =====================================================
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = "__all__"



# =====================================================
# ATTENDANCE SERIALIZER
# =====================================================



class AttendanceSerializer(serializers.ModelSerializer):
    punch_in_time = serializers.DateTimeField(read_only=True)
    punch_out_time = serializers.DateTimeField(read_only=True)

    date = serializers.DateField(read_only=True)

    class Meta:
        model = Attendance
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)

        if instance.punch_in_time:
            data["punch_in_time"] = timezone.localtime(
                instance.punch_in_time
            ).strftime("%Y-%m-%d %H:%M:%S")

        if instance.punch_out_time:
            data["punch_out_time"] = timezone.localtime(
                instance.punch_out_time
            ).strftime("%Y-%m-%d %H:%M:%S")

        return data



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

