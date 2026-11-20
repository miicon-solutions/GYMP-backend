# Attendance

Member month calendar/session adjust and device check-in/out.

- **OpenAPI:** `/openapi/v1/attendance.yaml`
- **Auth:** Bearer member for calendar; `X-Device-Key` for internal device routes

### Sample — device check-in

```http
POST /api/v1/internal/attendance/check-in/
X-Device-Key: <ATTENDANCE_DEVICE_KEY>
Content-Type: application/json

{"member_id": "PF-0001", "source": "device"}
```

`member_id` may be display `PF-…` or staff `short_id`. Duplicate same Asia/Dhaka day returns `recorded: false`.

Member calendar: `GET /api/v1/member/attendance/?year=&month=`.
