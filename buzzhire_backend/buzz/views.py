from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .models import Attendance, AttendanceCorrectionRequest, LeaveRequest, EmployeeLeaveBucket, WFHRequest
from .serializers import AttendanceSerializer, WFHRequestSerializer
from .utils.distance_utils import calculate_distance
from .constants import BRANCHES, PUNCH_RADIUS
from rest_framework import status
from django.conf import settings
from django.contrib.auth import get_user_model
from google.oauth2 import id_token
from google.auth.transport import requests
from rest_framework_simplejwt.tokens import RefreshToken
from datetime import datetime, time, timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Sum
from django.db import transaction

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
                date = timezone.localdate(),
                punch_in_time=timezone.now(),
                punch_in_lat=user_lat,
                punch_in_lon=user_lon,
                branch_name = nearest_branch["name"],
                work_status = "WFO"
            )
            message = "Punch in successful"
            print(attendance.date)

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



def seconds_to_hh_mm(seconds):
    if seconds is None:
        return None

    total_minutes = seconds // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60

    return f"{hours}:{minutes:02}"

class TotalHoursView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        start_date = parse_date(request.query_params.get("start_date"))
        end_date = parse_date(request.query_params.get("end_date"))

        if not start_date or not end_date or start_date > end_date:
            return Response(
                {"status": "failed", "message": "Invalid date range"},
                status=400
            )

        # Fetch attendance records
        attendances = Attendance.objects.filter(
            user=user,
            date__range=(start_date, end_date)
        ).order_by("date")

        # 1️⃣ Prepare all dates
        result = {}
        current_date = start_date
        while current_date <= end_date:
            result[current_date.isoformat()] = {
                "date": current_date.isoformat(),
                "punch_in_time": None,
                "punch_out_time": None,
                "working_time": None
            }
            current_date += timedelta(days=1)

        # 2️⃣ Fill attendance data
        for att in attendances:
            local_punch_in = timezone.localtime(att.punch_in_time)
            day = local_punch_in.date().isoformat()

            punch_out = (
                timezone.localtime(att.punch_out_time)
                if att.punch_out_time else None
            )

            working_time = None
            if punch_out:
                total_seconds = int((punch_out - local_punch_in).total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                working_time = f"{hours}:{minutes:02}"

            result[day] = {
                "date": day,
                "punch_in_time": local_punch_in.strftime("%H:%M"),
                "punch_out_time": punch_out.strftime("%H:%M") if punch_out else None,
                "working_time": working_time
            }

        return Response({
            "status": "success",
            "data": list(result.values())
        }, status=200)


################################################
# TOTAL DETAILS OF ALL EMPS FOR SELECTING DATES #
################################################


class AdminAttendanceReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 1️⃣ Read start_date (MANDATORY)
        start_date = parse_date(request.query_params.get("start_date"))
        if not start_date:
            return Response(
                {"error": "start_date is required"},
                status=400
            )

        # 2️⃣ Read end_date (OPTIONAL)
        end_date_param = request.query_params.get("end_date")
        end_date = parse_date(end_date_param) if end_date_param else start_date

        if start_date > end_date:
            return Response(
                {"error": "start_date cannot be greater than end_date"},
                status=400
            )

        # 3️⃣ Read optional employee IDs
        ids_param = request.query_params.get("ids")
        if ids_param:
            ids_list = [int(i) for i in ids_param.split(",") if i.isdigit()]
            employees = User.objects.filter(id__in=ids_list, is_staff=False)
        else:
            employees = User.objects.filter(is_staff=False)

        response_data = []

        # 4️⃣ Loop employees
        for employee in employees:
            employee_data = {
                "emp_id": employee.id,
                "employee_name": employee.name,
                "attendance": []
            }

            current_date = start_date
            while current_date <= end_date:

                # IST day range
                day_start = timezone.make_aware(
                    datetime.combine(current_date, time.min)
                )
                day_end = timezone.make_aware(
                    datetime.combine(current_date, time.max)
                )

                attendance = Attendance.objects.filter(
                    user=employee,
                    punch_in_time__range=(day_start, day_end)
                ).order_by("-id").first()

                punch_in = None
                punch_out = None
                total_time = None

                if attendance:
                    if attendance.punch_in_time:
                        punch_in = timezone.localtime(attendance.punch_in_time)

                    if attendance.punch_out_time:
                        punch_out = timezone.localtime(attendance.punch_out_time)

                    if punch_in and punch_out:
                        total_seconds = int((punch_out - punch_in).total_seconds())
                        hours = total_seconds // 3600
                        minutes = (total_seconds % 3600) // 60
                        total_time = f"{hours}:{minutes:02}"

                employee_data["attendance"].append({
                    "date": current_date.isoformat(),
                    "punch_in": punch_in.strftime("%H:%M") if punch_in else None,
                    "punch_out": punch_out.strftime("%H:%M") if punch_out else None,
                    "total_time": total_time
                })

                current_date += timedelta(days=1)

            response_data.append(employee_data)

        return Response({
            "status": "success",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "emps": response_data
        }, status=status.HTTP_200_OK)



class CreateAttendanceRegularizationRequest(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user   # 🔒 SAFE: derived from token

        date_str = request.data.get("date")
        req_type = request.data.get("type")      # PUNCH_IN / PUNCH_OUT
        time_str = request.data.get("time")      # HH:mm
        reason = request.data.get("reason")

        # 1️⃣ Validate inputs
        if not all([date_str, req_type, time_str, reason]):
            return Response(
                {"status": "failed", "message": "All fields are required"},
                status=400
            )

        if req_type not in ["PUNCH_IN", "PUNCH_OUT"]:
            return Response(
                {"status": "failed", "message": "Invalid type"},
                status=400
            )

        # 2️⃣ Parse & validate date (IST)
        req_date = parse_date(date_str)
        if not req_date:
            return Response(
                {"status": "failed", "message": "Invalid date format"},
                status=400
            )

        # ❌ Block future dates
        if req_date > timezone.localdate():
            return Response(
                {"status": "failed", "message": "Future date correction not allowed"},
                status=400
            )

        # 3️⃣ Build IST day range
        start_of_day = timezone.make_aware(
            datetime.combine(req_date, time.min)
        )
        end_of_day = timezone.make_aware(
            datetime.combine(req_date, time.max)
        )

        attendance = Attendance.objects.filter(
            user=user,
            punch_in_time__range=(start_of_day, end_of_day)
        ).order_by("-id").first()

        if not attendance:
            return Response(
                {"status": "failed", "message": "No attendance found for this date"},
                status=404
            )

        # 4️⃣ Parse requested time (IST)
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
            return Response(
                {"status": "failed", "message": "Invalid time format (HH:mm required)"},
                status=400
            )

        requested_datetime = timezone.make_aware(
            datetime.combine(req_date, time(hour, minute))
        )

        # 5️⃣ Prevent duplicate pending request
        if AttendanceCorrectionRequest.objects.filter(
            user=user,
            attendance=attendance,
            request_type=req_type,
            status="PENDING"
        ).exists():
            return Response(
                {"status": "failed", "message": "Pending request already exists"},
                status=400
            )

        # 6️⃣ Create correction request
        AttendanceCorrectionRequest.objects.create(
            user=user,
            attendance=attendance,
            request_type=req_type,
            requested_time=requested_datetime,
            reason=reason
        )

        return Response(
            {
                "status": "success",
                "message": "Attendance regularization request submitted"
            },
            status=status.HTTP_201_CREATED
        )


class AdminCorrectionDetail(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        # if request.user.role != "ADMIN":
        #     return Response({"detail": "Forbidden"}, status=403)

        correction = AttendanceCorrectionRequest.objects.select_related(
            "attendance", "user"
        ).filter(
            approval_token=token
        ).first()

        if not correction:
            return Response(
                {"status": "failed", "message": "Invalid link"},
                status=404
            )

        attendance_date = timezone.localtime(
            correction.attendance.punch_in_time
        ).date()

        requested_time_ist = timezone.localtime(
            correction.requested_time
        )

        return Response({
            "status": "success",
            "data": {
                "employee": correction.user.email,
                "date": attendance_date.isoformat(),
                "type": correction.request_type,
                "requested_time": requested_time_ist.strftime("%Y-%m-%d %H:%M"),
                "reason": correction.reason,
                "status": correction.status
            }
        })
    

class AdminApproveRejectCorrection(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        # if request.user.role != "ADMIN":
        #     return Response({"detail": "Forbidden"}, status=403)

        action = request.data.get("action")  # APPROVE / REJECT
        admin_comment = request.data.get("admin_comment", "")

        correction = AttendanceCorrectionRequest.objects.select_related(
            "attendance", "user"
        ).filter(
            approval_token=token,
            status="PENDING"
        ).first()

        if not correction:
            return Response(
                {"status": "failed", "message": "Invalid or processed request"},
                status=400
            )

        attendance = correction.attendance

        if action == "APPROVE":

            requested_time = correction.requested_time  # already timezone-aware

            # ---- LOGICAL VALIDATIONS ----
            if correction.request_type == "PUNCH_IN":
                if attendance.punch_out_time and requested_time >= attendance.punch_out_time:
                    return Response(
                        {"status": "failed", "message": "Punch-in cannot be after punch-out"},
                        status=400
                    )
                attendance.punch_in_time = requested_time

            elif correction.request_type == "PUNCH_OUT":
                if requested_time <= attendance.punch_in_time:
                    return Response(
                        {"status": "failed", "message": "Punch-out cannot be before punch-in"},
                        status=400
                    )
                attendance.punch_out_time = requested_time

            else:
                return Response(
                    {"status": "failed", "message": "Invalid request type"},
                    status=400
                )

            attendance.save()
            correction.status = "APPROVED"

        elif action == "REJECT":
            correction.status = "REJECTED"

        else:
            return Response(
                {"status": "failed", "message": "Invalid action"},
                status=400
            )

        correction.admin_comment = admin_comment
        correction.save()

        # 📧 Email with IST times
        requested_time_ist = timezone.localtime(correction.requested_time)

        return Response({
            "status": "success",
            "message": f"Request {correction.status.lower()}"
        })


class EmployeeAttendanceCorrectionRequests(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        requests = AttendanceCorrectionRequest.objects.filter(
            user=user
        ).select_related("attendance").order_by("-created_at")

        data = []
        for req in requests:
            requested_time_ist = timezone.localtime(req.requested_time)

            data.append({
                "id": req.id,
                "date": requested_time_ist.date().isoformat(),
                "type": req.request_type,
                "requested_time": requested_time_ist.strftime("%H:%M"),
                "reason": req.reason,
                "status": req.status,
                "admin_comment": req.admin_comment,
                "created_at": timezone.localtime(req.created_at).isoformat()
            })

        return Response({
            "status": "success",
            "data": data
        })
    

class AdminAttendanceCorrectionList(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # if request.user.role != "ADMIN":
        #     return Response({"detail": "Forbidden"}, status=403)

        status_filter = request.query_params.get("status")  # PENDING / APPROVED / REJECTED

        qs = AttendanceCorrectionRequest.objects.select_related(
            "user", "attendance"
        ).order_by("-created_at")

        if status_filter:
            qs = qs.filter(status=status_filter)

        data = []
        for req in qs:
            requested_time_ist = timezone.localtime(req.requested_time)

            data.append({
                "id": req.id,
                "employee": req.user.name,
                "date": requested_time_ist.date().isoformat(),
                "type": req.request_type,
                "requested_time": requested_time_ist.strftime("%H:%M"),
                "reason": req.reason,
                "approval_token": req.approval_token,
                "status": req.status,
                "created_at": timezone.localtime(req.created_at).isoformat()
            })

        return Response({
            "status": "success",
            "count": len(data),
            "data": data
        })
    

class EmployeeCancelAttendanceCorrectionRequest(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, request_id):
        user = request.user

        req = AttendanceCorrectionRequest.objects.filter(
            id=request_id,
            user=user,
            status="PENDING"
        ).first()

        if not req:
            return Response(
                {"status": "failed", "message": "Request not found or already processed"},
                status=400
            )

        req.status = "CANCELLED"
        req.save(update_fields=["status"])

        return Response({
            "status": "success",
            "message": "Request cancelled"
        })



class ApplyLeaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        start_date_str = request.data.get("start_date")
        end_date_str = request.data.get("end_date")
        reason = request.data.get("reason")

        # 1️⃣ Validate inputs
        if not all([start_date_str, end_date_str, reason]):
            return Response(
                {"message": "start_date, end_date and reason are required"},
                status=400
            )

        # 2️⃣ Parse dates safely
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)

        if not start_date or not end_date:
            return Response(
                {"message": "Invalid date format (YYYY-MM-DD required)"},
                status=400
            )

        # 3️⃣ Validate date logic
        if start_date > end_date:
            return Response(
                {"message": "start_date cannot be greater than end_date"},
                status=400
            )

        # ❌ Optional: block past leave
        if start_date < timezone.localdate():
            return Response(
                {"message": "Cannot apply leave for past dates"},
                status=400
            )

        # 4️⃣ Calculate total days (inclusive)
        total_days = (end_date - start_date).days + 1

        # 5️⃣ Create leave request
        leave = LeaveRequest.objects.create(
            user=user,
            start_date=start_date,
            end_date=end_date,
            total_days=total_days,
            reason=reason,
            status="PENDING"
        )

        return Response(
            {
                "message": "Leave applied successfully",
                "leave_id": leave.id,
                "requested_days": total_days,
                "status": leave.status
            },
            status=status.HTTP_201_CREATED
        )
    


class EmployeeLeaveSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # ---------- 1️⃣ Fetch leave bucket ----------
        leave_bucket, _ = EmployeeLeaveBucket.objects.get_or_create(
            user=user
        )

        # ---------- 2️⃣ Fetch leave requests ----------
        leave_requests = LeaveRequest.objects.filter(
            user=user
        ).order_by("-created_at")

        # ---------- 3️⃣ Aggregate leave stats ----------
        def get_days_by_status(status):
            return (
                leave_requests
                .filter(status=status)
                .aggregate(total=Sum("total_days"))
                .get("total") or 0
            )

        approved_days = get_days_by_status("APPROVED")
        pending_days = get_days_by_status("PENDING")
        rejected_days = get_days_by_status("REJECTED")
        cancelled_days = get_days_by_status("CANCELLED")

        # ---------- 4️⃣ Serialize leave requests ----------
        requests_data = []
        for leave in leave_requests:
            requests_data.append({
                "id": leave.id,
                "start_date": leave.start_date.isoformat(),
                "end_date": leave.end_date.isoformat(),
                "total_days": leave.total_days,
                "reason": leave.reason,
                "status": leave.status,
                "applied_on": leave.created_at.date().isoformat()
            })

        # ---------- 5️⃣ Final response ----------
        return Response({
            "status": "success",
            "leave_summary": {
                "total_leave": leave_bucket.total_leave,
                "taken_leave": leave_bucket.taken_leave,
                "remaining_leave": leave_bucket.remaining_leave,
            },
            "leave_stats": {
                "approved_days": approved_days,
                "pending_days": pending_days,
                "rejected_days": rejected_days,
                "cancelled_days": cancelled_days,
            },
            "leave_requests": requests_data
        })



class AdminLeaveActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, leave_id):

        # 🔐 Admin-only
        # if request.user.role != "ADMIN":
        #     return Response(
        #         {"error": "Forbidden"},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        action = request.data.get("action")  # APPROVE / REJECT

        if action not in ["APPROVE", "REJECT"]:
            return Response(
                {"error": "Invalid action. Use APPROVE or REJECT"},
                status=status.HTTP_400_BAD_REQUEST
            )

        leave = LeaveRequest.objects.select_related("user").filter(
            id=leave_id
        ).first()

        if not leave:
            return Response(
                {"error": "Leave request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if leave.status != "PENDING":
            return Response(
                {"error": "Leave already processed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = leave.user

        # ===============================
        #  APPROVE LEAVE
        # ===============================
        if action == "APPROVE":
            with transaction.atomic():

                bucket = EmployeeLeaveBucket.objects.select_for_update().filter(
                    user=user
                ).first()

                if not bucket:
                    return Response(
                        {"error": "Leave bucket not found"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                days = leave.total_days

                # 🔄 Update leave bucket (NO BALANCE BLOCK)
                bucket.taken_leave += days
                bucket.remaining_leave -= days  # can go negative
                bucket.save()

                # 🟢 MARK ATTENDANCE AS LEAVE (INLINE LOGIC)
                current_date = leave.start_date

                while current_date <= leave.end_date:

                    attendance = Attendance.objects.filter(
                        user=user,
                        date=current_date
                    ).first()

                    if attendance:
                        # Update existing attendance
                        attendance.work_status = "LEAVE"
                        attendance.save(update_fields=["work_status"])
                    else:
                        # Create new attendance entry
                        Attendance.objects.create(
                            user=user,
                            date=current_date,
                            work_status="LEAVE"
                        )

                    current_date += timedelta(days=1)

                # ✅ Approve leave
                leave.status = "APPROVED"
                leave.save(update_fields=["status"])

            return Response(
                {
                    "message": "Leave approved successfully",
                    "approved_days": days,
                    "total_leave": bucket.total_leave,
                    "taken_leave": bucket.taken_leave,
                    "remaining_leave": bucket.remaining_leave
                },
                status=status.HTTP_200_OK
            )

        # ===============================
        #  REJECT LEAVE
        # ===============================
        leave.status = "REJECTED"
        leave.save(update_fields=["status"])

        return Response(
            {"message": "Leave rejected successfully"},
            status=status.HTTP_200_OK
        )


class AdminLeaveListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 🔐 Admin check
        # if request.user.role != "ADMIN":
        #     return Response(
        #         {"error": "Forbidden"},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        status_filter = request.query_params.get("status")

        # 🔹 base queryset (optimized)
        leaves_qs = LeaveRequest.objects.select_related("user").order_by("-created_at")

        # 🔹 optional status filter
        if status_filter:
            if status_filter not in ["PENDING", "APPROVED", "REJECTED", "CANCELLED"]:
                return Response(
                    {"error": "Invalid status filter"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            leaves_qs = leaves_qs.filter(status=status_filter)

        data = []

        for leave in leaves_qs:
            data.append({
                "leave_id": leave.id,
                "user_id": leave.user.id,
                "user_name": leave.user.name,
                "user_email": leave.user.email,
                "start_date": leave.start_date.isoformat(),
                "end_date": leave.end_date.isoformat(),
                "total_days": leave.total_days,
                "reason": leave.reason,
                "status": leave.status,
                "applied_at": timezone.localtime(leave.created_at).isoformat(),
            })

        return Response(
            {
                "count": len(data),
                "results": data
            },
            status=status.HTTP_200_OK
        )


class ApplyWFHView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        date_str = request.data.get("date")

        # 1️⃣ Validate input
        if not date_str:
            return Response(
                {"message": "date is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        wfh_date = parse_date(date_str)
        if not wfh_date:
            return Response(
                {"message": "Invalid date format (YYYY-MM-DD required)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2️⃣ Prevent past dates
        if wfh_date < timezone.localdate():
            return Response(
                {"message": "Cannot apply WFH for past dates"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3️⃣ Prevent duplicate request
        if WFHRequest.objects.filter(user=user, date=wfh_date).exists():
            return Response(
                {"message": "WFH already applied for this date"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 4️⃣ Prevent WFH on approved leave
        if LeaveRequest.objects.filter(
            user=user,
            status="APPROVED",
            start_date__lte=wfh_date,
            end_date__gte=wfh_date
        ).exists():
            return Response(
                {"message": "Cannot apply WFH on an approved leave"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 5️⃣ Create WFH request
        wfh = WFHRequest.objects.create(
            user=user,
            date=wfh_date,
            status="PENDING"
        )

        # 6️⃣ Notify (async recommended later)
        # send_wfh_apply_email(user, wfh)

        return Response(
            WFHRequestSerializer(wfh).data,
            status=status.HTTP_201_CREATED
        )


class EmployeeWFHRequestsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        wfh_requests = (
            WFHRequest.objects
            .filter(user=user)
            .order_by("-created_at")
        )

        data = []

        for wfh in wfh_requests:
            data.append({
                "wfh_id": wfh.id,
                "date": wfh.date.isoformat(),
                "status": wfh.status,
                "applied_at": timezone.localtime(wfh.created_at).isoformat(),
                "actioned_at": (
                    timezone.localtime(wfh.updated_at).isoformat()
                    if wfh.status in ["APPROVED", "REJECTED"]
                    else None
                )
            })

        return Response(
            {
                "count": len(data),
                "results": data
            },
            status=status.HTTP_200_OK
        )

class AdminWFHActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, wfh_id):
        # 🔐 Admin-only
        # if request.user.role != "ADMIN":
        #     return Response(
        #         {"error": "Forbidden"},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        action = request.data.get("action")  # APPROVE / REJECT
        if action not in ["APPROVE", "REJECT"]:
            return Response(
                {"error": "Invalid action. Use APPROVE or REJECT"},
                status=status.HTTP_400_BAD_REQUEST
            )

        wfh = WFHRequest.objects.select_related("user").filter(
            id=wfh_id
        ).first()

        if not wfh:
            return Response(
                {"error": "WFH request not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        if wfh.status != "PENDING":
            return Response(
                {"error": "WFH request already processed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ===============================
        #  REJECT WFH
        # ===============================
        if action == "REJECT":
            wfh.status = "REJECTED"
            wfh.save(update_fields=["status"])

            return Response(
                {"message": "WFH request rejected"},
                status=status.HTTP_200_OK
            )

        # ===============================
        #  APPROVE WFH
        # ===============================
        with transaction.atomic():

            wfh.status = "APPROVED"
            wfh.save(update_fields=["status"])

            wfh_date = wfh.date
            today = timezone.localdate()

            # Past-date safety (do not backfill attendance)
            if wfh_date < today:
                return Response(
                    {
                        "message": "WFH approved (past date – attendance not created)",
                        "attendance_created": False,
                        "attendance_date": wfh_date
                    },
                    status=status.HTTP_200_OK
                )

            # Fixed WFH punch timings (IST)
            punch_in = timezone.make_aware(
                datetime.combine(wfh_date, time(9, 30))
            )
            punch_out = timezone.make_aware(
                datetime.combine(wfh_date, time(19, 0))
            )

            attendance = Attendance.objects.filter(
                user=wfh.user,
                date=wfh_date
            ).first()

            if attendance:
                attendance.work_status = "WFH"
                attendance.punch_in_time = punch_in
                attendance.punch_out_time = punch_out
                attendance.save(
                    update_fields=["work_status", "punch_in_time", "punch_out_time"]
                )
            else:
                Attendance.objects.create(
                    user=wfh.user,
                    date=wfh_date,
                    work_status="WFH",
                    punch_in_time=punch_in,
                    punch_out_time=punch_out
                )

        return Response(
            {
                "message": "WFH approved successfully",
                "attendance_created": True,
                "user": wfh.user.email,
                "attendance_date": wfh_date
            },
            status=status.HTTP_200_OK
        )


class AdminWFHListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # 🔐 Admin-only access
        # if request.user.role != "ADMIN":
        #     return Response(
        #         {"error": "Forbidden"},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        status_filter = request.query_params.get("status")

        # 🔹 Base queryset (optimized)
        wfh_qs = (
            WFHRequest.objects
            .select_related("user")
            .order_by("-created_at")
        )

        # 🔹 Optional status filter
        if status_filter:
            if status_filter not in ["PENDING", "APPROVED", "REJECTED"]:
                return Response(
                    {"error": "Invalid status filter"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            wfh_qs = wfh_qs.filter(status=status_filter)

        data = []

        for wfh in wfh_qs:
            data.append({
                "wfh_id": wfh.id,
                "user_id": wfh.user.id,
                "user_name": wfh.user.name,
                "user_email": wfh.user.email,
                "date": wfh.date.isoformat(),
                "status": wfh.status,
                "applied_at": timezone.localtime(wfh.created_at).isoformat(),
                "actioned_at": (
                    timezone.localtime(wfh.updated_at).isoformat()
                    if wfh.status in ["APPROVED", "REJECTED"]
                    else None
                )
            })

        return Response(
            {
                "count": len(data),
                "results": data
            },
            status=status.HTTP_200_OK
        )