import datetime
from ..models import CompanyWorkingRules, CompanyHoliday, HolidayOverride


def get_weekday_code(date):
    """
    Returns weekday code like MON, TUE, WED...
    """
    return date.strftime("%a").upper()[:3]


def is_working_day(date):
    """
    Final authority to decide if a date is a working day or not
    """

    # 1️⃣ Load company rules (assume single company for now)
    rules = CompanyWorkingRules.objects.first()

    if not rules:
        # Safety fallback: if no rules exist, assume working day
        return True

    weekday_code = get_weekday_code(date)

    # 2️⃣ Check base working rule (Mon-Fri usually)
    is_weekday_working = weekday_code in rules.working_days

    # 3️⃣ Check if it's a holiday (active only)
    holiday = CompanyHoliday.objects.filter(
        date=date,
        is_active=True
    ).first()

    # 4️⃣ Check if override exists for this date
    override = HolidayOverride.objects.filter(date=date).first()

    # ==========================
    # FINAL DECISION TREE
    # ==========================

    # Case A: Holiday exists and no override → holiday
    if holiday and not override:
        return False

    # Case B: Holiday exists but cancelled → working day
    if holiday and override and override.override_type == "CANCELLED":
        return True

    # Case C: Weekend but explicitly marked as working day
    if not is_weekday_working and override and override.override_type == "WORKING_DAY":
        return True

    # Case D: Comp-off override
    if override and override.override_type == "COMP_OFF":
        return False

    # Case E: Normal weekday
    if is_weekday_working:
        return True

    # Case F: Normal weekend
    return False
