# Staff

Staff CRUD, activate/deactivate, permissions catalog, MFA enroll reset, and staff fingerprint vault.

- **OpenAPI:** `/openapi/v1/staff.yaml`
- **Base path:** `/api/v1/admin/staff/`
- **Auth:** Bearer staff; identity mutations are SuperOnly

### Sample — permissions catalog

```http
GET /api/v1/admin/staff/permissions/catalog/
Authorization: Bearer <super_access_token>
```

`StaffProfile.permissions` is a list of `feature.action` codes. Empty list → no admin feature APIs for non-super staff.
