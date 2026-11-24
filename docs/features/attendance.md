# Attendance

Member month calendar/session adjust and device check-in/out.

- **OpenAPI:** `/openapi/v1/attendance.yaml`
- **Auth:** Bearer member for calendar; `X-Device-Key` for internal device routes

### Sample — device check-in

```http
POST /api/v1/internal/attendance/check-in/
X-Device-Key: <ATTENDANCE_DEVICE_KEY>
Content-Type: application/json

{"member_id": "000000001", "source": "device"}
```

`member_id` is the punch id from the scanner. Resolution order:

1. Staff `device_keypad_id` (digits; also matches zero-padded legacy rows)
2. Member `device_keypad_id`
3. Staff `short_id` / member display `member_id` (the paid 9-digit serial)

A signup id `PFT-######` is not a scanner id. Check-in of an unpaid member is refused.

Duplicate same Asia/Dhaka day returns `recorded: false`.
Member check-in is **403** when `membership_status` is `none`, `pending_payment`, or
`expired` (also when still `active` but `expires_on` is before the punch’s Dhaka date).

Member calendar: `GET /api/v1/member/attendance/?year=&month=`.
