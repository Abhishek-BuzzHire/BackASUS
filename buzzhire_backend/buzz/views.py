from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .models import Attendance
from .serializers import AttendanceSerializer
from .utils.distance_utils import calculate_distance
from .constants import BRANCHES, PUNCH_RADIUS
from rest_framework import status
from django.conf import settings
from django.contrib.auth import get_user_model
from google.oauth2 import id_token
from google.auth.transport import requests
from rest_framework_simplejwt.tokens import RefreshToken
from datetime import datetime, time
from django.utils import timezone

def get_ist_day_range():
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, time.min))
    end = timezone.make_aware(datetime.combine(today, time.max))
    return start, end

User = get_user_model()

class GoogleAuthView(APIView):
    def post(self, request):
        token = request.data.get("id_token")
        if not token:
            return Response({"error": "id_token required"}, status=400)

        try:
            info = id_token.verify_oauth2_token(
                token, 
                requests.Request(), 
                settings.GOOGLE_CLIENT_ID,
                clock_skew_in_seconds=300
            )

            email = info.get("email")
            name = info.get("name", email)
            picture = info.get("picture")

            if email not in settings.WHITELISTED_EMAILS:
                return Response({"error": "Not allowed"}, status=403)

            user, created = User.objects.get_or_create(
                email=email,
                defaults={"name": name,
                          "lastlogin": timezone.now()}
            )

            if not created:
                user.name = name 
                user.picture = picture
                user.lastlogin = timezone.now()
                user.save()

            refresh = RefreshToken.for_user(user)
            refresh["email"] = user.email
            refresh["name"] = user.name
            refresh["picture"] = user.picture


            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "email": email,
                "name": name,
                "picture": picture,
                "user_id": user.pk,
            })

        except ValueError as e:
            print(f"Google Token Verification Failed: {e}") 
            return Response({"error": f"Invalid token (details: {e})"}, status=400)
        except Exception as e:
            print(f"Authentication Error: {e}")
            return Response({"error": "Invalid token (internal error)"}, status=400)


def detect_branch(user_lat, user_lon):
    """
    Returns (True, branch_name, distance) if inside any branch range.
    Else returns (False, None, None)
    """

    for branch in BRANCHES:
        dist = calculate_distance(
            user_lat, user_lon,
            branch["lat"], branch["lon"]
        )

        if dist <= PUNCH_RADIUS:
            return True, branch["name"], dist

    return False, None, None

class PunchInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # 0️⃣ Validate input
        if "latitude" not in request.data or "longitude" not in request.data:
            return Response(
                {"status": "failed", "message": "latitude & longitude are required"},
                status=400
            )

        user_lat = float(request.data.get("latitude"))
        user_lon = float(request.data.get("longitude"))

        # 1️⃣ Check for today's attendance (latest record)
        today = timezone.localdate()

        start_of_day, end_of_day = get_ist_day_range()

        attendance = Attendance.objects.filter(
            user=user,
            punch_in_time__range=(start_of_day, end_of_day)
        ).order_by('-id').first()  # get latest attendance record

        # 2️⃣ Find nearest branch

        nearest_branch = None
        nearest_distance = float("inf")
        for b in BRANCHES:
            dist = calculate_distance(user_lat, user_lon, b["lat"], b["lon"])
            if dist < nearest_distance:
                nearest_distance = dist
                nearest_branch = b

        # 2.1️⃣ Check if user is in range
        if nearest_distance > PUNCH_RADIUS:
            return Response({
                "status": "failed",
                "message": "You are out of range",
                "nearest_branch": nearest_branch["name"],
                "distance": round(nearest_distance, 2)
            }, status=400)

        # 3️⃣ Handle punch-in logic
        if attendance:
            if attendance.punch_out_time is None:
                # Already punched in
                return Response({
                    "status": "failed",
                    "message": "You are already punched in today",
                    "data": AttendanceSerializer(attendance).data
                }, status=400)
            else:
                # Punched out before, update with new punch-in
                attendance.punch_in_time = timezone.now()
                attendance.punch_in_lat = user_lat
                attendance.punch_in_lon = user_lon
                attendance.punch_out_time = None  # reset punch out
                attendance.punch_out_lat = None
                attendance.punch_out_lon = None
                attendance.save()
                message = "Punch in updated successfully"
        else:
            # No attendance today, create new record
            attendance = Attendance.objects.create(
                user=user,
                punch_in_time=timezone.now(),
                punch_in_lat=user_lat,
                punch_in_lon=user_lon
            )
            message = "Punch in successful"

        return Response({
            "status": "success",
            "message": message + f" at {nearest_branch['name']}",
            "branch": nearest_branch["name"],
            "distance": round(nearest_distance, 2),
            "data": AttendanceSerializer(attendance).data
        }, status=201)



class PunchOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # 1️⃣ Validate inputs
        if "latitude" not in request.data or "longitude" not in request.data:
            return Response(
                {"status": "failed", "message": "latitude & longitude are required"},
                status=400
            )

        user_lat = float(request.data.get("latitude"))
        user_lon = float(request.data.get("longitude"))

        start_of_day, end_of_day = get_ist_day_range()

        # 2️⃣ Find today’s active punch-in
        today = timezone.localdate()
        attendance = Attendance.objects.filter(
            user=user,
            punch_in_time__range=(start_of_day, end_of_day),
            punch_out_time__isnull=True
        ).first()

        if not attendance:
            return Response({
                "status": "failed",
                "message": "You have not punched in today"
            }, status=400)

        # 3️⃣ Find nearest branch
        nearest_branch = None
        min_distance = float("inf")

        for branch in BRANCHES:
            dist = calculate_distance(user_lat, user_lon, branch["lat"], branch["lon"])
            if dist < min_distance:
                min_distance = dist
                nearest_branch = branch

        distance = min_distance

        # Range check
        if distance > PUNCH_RADIUS:
            return Response({
                "status": "failed",
                "message": f"You are out of range for {nearest_branch['name']}",
                "distance": round(distance, 2),
                "branch": nearest_branch["name"]
            }, status=400)

        # 4️⃣ Save punch-out
        attendance.punch_out_time = timezone.now()
        attendance.punch_out_lat = user_lat
        attendance.punch_out_lon = user_lon
        attendance.save()

        return Response({
            "status": "success",
            "message": f"Punch out successful",
            "branch": nearest_branch["name"],
            "distance": round(distance, 2),
            "data": AttendanceSerializer(attendance).data
        }, status=200)

class TodayAttendanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.localdate()

        start_of_day = timezone.make_aware(
            datetime.combine(today, time.min)
        )
        end_of_day = timezone.make_aware(
            datetime.combine(today, time.max)
        )

        # Get latest attendance for today
        attendance = Attendance.objects.filter(
            user=user,
            punch_in_time__range=(start_of_day, end_of_day)
        ).order_by('-id').first()

        if not attendance:
            # User has not punched in today at all
            return Response({
                "status": "success",
                "data": {
                    "is_punched_in": False,
                    "has_punched_out": False,
                    "punch_in_time": None,
                    "punch_out_time": None,
                    "branch": None,
                    "distance": None
                }
            }, status=200)
        
        punch_in_time = timezone.localtime(attendance.punch_in_time)
        punch_out_time = (
            timezone.localtime(attendance.punch_out_time)
            if attendance.punch_out_time else None
        )

        # Determine status flags
        is_punched_in = attendance.punch_in_time is not None
        has_punched_out = attendance.punch_out_time is not None

        print("punchInTime:", attendance.punch_in_time)
        print("punchOutTime:", attendance.punch_out_time)

        return Response({
            "status": "success",
            "data": {
                "is_punched_in": attendance.punch_out_time is None,
                "has_punched_out": attendance.punch_out_time is not None,
                "punch_in_time": punch_in_time,
                "punch_out_time": punch_out_time,
                "branch": getattr(attendance, "branch_name", None),  # optional, safe
                "distance": None,   # distance only calculated at punch time
                "raw": AttendanceSerializer(attendance).data
            }
        }, status=200)


class TotalWorkingTimeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.localdate()

        start_of_day, end_of_day = get_ist_day_range()

        attendance = Attendance.objects.filter(
            user=user,
            punch_in_time__range=(start_of_day, end_of_day)
        ).order_by("-id").first()

        start = timezone.localtime(attendance.punch_in_time)
        end = timezone.localtime(attendance.punch_out_time or timezone.now())

        total_seconds = max(0, int((end - start).total_seconds()))

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        formatted_time = f"{hours}.{minutes:02}"

        print("START TIME:", start)
        print("END TIME:", end)
        print("Work TIME:", formatted_time)

        return Response({
            "total_working_time": formatted_time
        }, status=200)


class AttendanceRangeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if not start_date or not end_date:
            return Response(
                {
                    "status": "failed",
                    "message": "start_date and end_date are required (YYYY-MM-DD)"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {
                    "status": "failed",
                    "message": "Invalid date format. Use YYYY-MM-DD"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch all attendance records in range
        records = Attendance.objects.filter(
            user=user,
            punch_in_time__date__range=(start_date, end_date)
        ).order_by("punch_in_time")

        grouped_data = {}

        for att in records:
            day = att.punch_in_time.date()

            # Keep latest entry per day (same as TodayAttendanceView logic)
            grouped_data[day] = att

        response_data = []

        for day, att in grouped_data.items():
            punch_in = att.punch_in_time
            punch_out = att.punch_out_time

            working_seconds = None
            if punch_in and punch_out:
                working_seconds = int(
                    (punch_out - punch_in).total_seconds()
                )

            response_data.append({
                "date": day,
                "punch_in_time": punch_in,
                "punch_out_time": punch_out,
                "working_seconds": working_seconds
            })

        return Response(
            {
                "status": "success",
                "data": response_data
            },
            status=status.HTTP_200_OK
        )