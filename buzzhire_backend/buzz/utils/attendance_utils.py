from datetime import timedelta
from buzz.models import Attendance


def mark_leave_attendance(user, start_date, end_date):
    """
    Leave approve hone par attendance table me LEAVE mark kare
    """

    current_date = start_date

    while current_date <= end_date:

        # agar already attendance hai to skip
        if not Attendance.objects.filter(
            user_id=user.id,
            date=current_date
        ).exists():
            Attendance.objects.create(
                user_id=user.id,
                date=current_date,
                work_status="LEAVE"
            )

        current_date += timedelta(days=1)
