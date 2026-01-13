from django.urls import path
from .views import PunchInView, PunchOutView, TodayAttendanceView, TotalWorkingTimeView, TotalHoursView, AdminAttendanceReportView, CreateAttendanceRegularizationRequest, AdminCorrectionDetail, AdminApproveRejectCorrection, AdminAttendanceCorrectionList, EmployeeAttendanceCorrectionRequests, EmployeeCancelAttendanceCorrectionRequest, AdminLeaveListView, AdminLeaveActionView, ApplyLeaveView, EmployeeLeaveSummaryView, EmployeeWFHRequestsView, ApplyWFHView, AdminWFHListView, AdminWFHActionView, AdminCompanyWorkingRulesView,AdminCompanyWorkingRulesDetailView, AdminHolidayListCreateView, AdminHolidayDetailView, AdminHolidayOverrideListCreateView, AdminHolidayOverrideDeleteView
from .views import GoogleAuthView


urlpatterns = [
    path("google/", GoogleAuthView.as_view()),

    # Attendence
    path("punch-in/", PunchInView.as_view(), name="punch-in"),
    path("punch-out/", PunchOutView.as_view(), name="punch-out"),
    path("today/", TodayAttendanceView.as_view()),
    path('total-working-time/', TotalWorkingTimeView.as_view()),
    path("total-hours/", TotalHoursView.as_view()),
    path("api/admin/emp-total-details/", AdminAttendanceReportView.as_view(), name = "emps-total-details"),
    path("api/attendance-correction/request/", CreateAttendanceRegularizationRequest.as_view(), name="attendance-correction-request"),
    path(
        "api/attendance-regularization/my-requests/", EmployeeAttendanceCorrectionRequests.as_view(), name="my-attendance-correction-requests",
    ),

    path(
        "api/attendance-regularization/cancel/<int:request_id>/", EmployeeCancelAttendanceCorrectionRequest.as_view(), name="cancel-attendance-correction-request",
    ),
    path("api/admin/attendance-approval/<str:token>/", AdminCorrectionDetail.as_view(), name="admin-attendance-correction-detail"
    ),
    path("api/admin/attendance-approval/<str:token>/action/", AdminApproveRejectCorrection.as_view(), name="admin-attendance-correction-action"
    ),
    path(
        "api/admin/attendance-regularization/requests/", AdminAttendanceCorrectionList.as_view(), name="admin-attendance-correction-list",
    ),
    path("api/admin/leaves/", AdminLeaveListView.as_view()), # master list of leaves for admin
    path( "api/admin/leaves/<int:leave_id>/action/", AdminLeaveActionView.as_view()),  # admin ke liye leave approve/reject karne,

    path("api/employee/leave/apply/", ApplyLeaveView.as_view(), name="apply-leave"),

    path("api/employee/leave/summary/", EmployeeLeaveSummaryView.as_view(), name="my-leave-summary"),

    path("wfh/apply/", ApplyWFHView.as_view(), name="apply-wfh"),

    path("wfh/my-requests/", EmployeeWFHRequestsView.as_view(), name="my-wfh-requests"),

    path("wfh/admin/requests/", AdminWFHListView.as_view(), name="admin-wfh-list"),

    path("wfh/admin/action/<int:wfh_id>/", AdminWFHActionView.as_view(), name="admin-wfh-action"),

    # Working rules
    path("admin/working-rules/", AdminCompanyWorkingRulesView.as_view()),
    path("admin/working-rules/<int:rule_id>/", AdminCompanyWorkingRulesDetailView.as_view()),

    # Holidays
    path("admin/holidays/", AdminHolidayListCreateView.as_view()),
    path("admin/holidays/<int:holiday_id>/", AdminHolidayDetailView.as_view()),

    # Overrides
    path("admin/overrides/", AdminHolidayOverrideListCreateView.as_view()),
    path("admin/overrides/<int:override_id>/", AdminHolidayOverrideDeleteView.as_view()),

]