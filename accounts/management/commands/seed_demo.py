from collections import Counter
from datetime import datetime, time, timedelta
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.crypto import normalize_phone
from accounts.identifiers import next_display
from accounts.models import StaffProfile, User
from accounts.services import lock_key
from attendance.models import CheckIn
from members.models import MemberProfile
from operations.models import Activity, Cost, Holiday
from operations.services import DHAKA, seed_hours
from payments.models import Payment, PaymentSession
from payments.services import format_taka, go_add_months
from plans.models import Offer, Plan
from plans.services import pricing


def demo_id(kind, key):
    return uuid5(NAMESPACE_URL, f"https://puregym.fit/demo/v1/{kind}/{key}")


class Command(BaseCommand):
    help = "Create repeatable local/development demo data using an existing super admin."

    def add_arguments(self, parser):
        parser.add_argument("--admin-phone", required=True)
        parser.add_argument("--members", type=int, default=30)

    def handle(self, *args, **options):
        if settings.APP_ENV == "prod":
            raise CommandError("Demo seed data is disabled in production.")
        if not 1 <= options["members"] <= 1000:
            raise CommandError("--members must be between 1 and 1000.")
        try:
            phone = normalize_phone(options["admin_phone"])
        except ValidationError as exc:
            raise CommandError("Enter a valid super admin phone number.") from exc
        self.counts = Counter()
        self.skipped = Counter()
        self.today = timezone.localdate()
        self.member_phones = []
        try:
            with transaction.atomic():
                lock_key("seed:demo:v1")
                self.actor = User.objects.filter(
                    phone_e164=phone, role="admin", is_active=True, is_superuser=True
                ).first()
                if not self.actor or not StaffProfile.objects.filter(user=self.actor).exists():
                    raise CommandError("Bootstrap an active super admin before running seed_demo.")
                self.seed(options["members"])
        except IntegrityError as exc:
            raise CommandError(
                "Demo data conflicts with existing records; nothing was changed."
            ) from exc
        self.stdout.write(self.style.SUCCESS("Demo data ready (no external services contacted)."))
        for label in sorted(self.counts.keys() | self.skipped.keys()):
            self.stdout.write(
                f"{label}: created {self.counts[label]}, skipped {self.skipped[label]}"
            )
        self.stdout.write(
            "Demo member phones (use the configured OTP provider/development bypass):"
        )
        for phone in self.member_phones:
            self.stdout.write(phone)
        self.stdout.write(
            "Sample staff have no password or MFA enrollment. Use admin MFA setup to enroll."
        )

    def put(self, model, key, **values):
        row, created = model.objects.get_or_create(
            pk=demo_id(model._meta.label_lower, key), defaults=values
        )
        (self.counts if created else self.skipped)[model._meta.verbose_name_plural] += 1
        return row, created

    def account(self, key, phone, name, role):
        pk = demo_id("user", key)
        if User.objects.filter(phone_e164=phone).exclude(pk=pk).exists():
            raise CommandError(f"Phone collision for demo {key}; nothing was changed.")
        user = User.objects.filter(pk=pk).first()
        if user:
            self.skipped["users"] += 1
            return user, False
        user = User.objects.create_user(phone, id=pk, full_name=name, role=role)
        self.counts["users"] += 1
        return user, True

    def activity(self, key, area, action, summary_key, params, day=None):
        row, created = self.put(
            Activity,
            key,
            admin=self.actor,
            admin_name=self.actor.full_name,
            admin_short_id=self.actor.staff_profile.short_id,
            area=area,
            action=action,
            summary_key=summary_key,
            summary_params=params,
        )
        if created and day:
            Activity.objects.filter(pk=row.pk).update(created_at=self.at(day))

    def at(self, day):
        return min(datetime.combine(day, time(10), tzinfo=DHAKA), timezone.now())

    def seed(self, count):
        seed_hours()
        plans = []
        for catalog, months, reduction in [
            ("monthly", 1, 0),
            ("quarterly", 3, 500),
            ("annual", 12, 3500),
        ]:
            plan = Plan.objects.filter(duration_months=months).first()
            if plan:
                self.skipped["plans"] += 1
            else:
                plan, _ = self.put(
                    Plan,
                    catalog,
                    catalog_id=catalog,
                    name=catalog.title(),
                    duration_months=months,
                    monthly_rate_taka=1500,
                    admission_fee_taka=1500,
                    discount_type="amount" if reduction else "none",
                    discount_value=reduction,
                )
                self.activity(
                    f"plan-{catalog}",
                    "plan",
                    "create",
                    "adminActivityPlanCreated",
                    {"name": plan.name},
                )
            plans.append(plan)
        annual = plans[-1]
        if annual.pk == demo_id("plans.plan", "annual"):
            for key, start, end in [("past", -80, -60), ("current", -5, 14)]:
                self.put(
                    Offer,
                    key,
                    plan=annual,
                    name=f"Demo {key} admission offer",
                    starts_on=self.today + timedelta(days=start),
                    ends_on=self.today + timedelta(days=end),
                    waive_admission=True,
                    is_active=key == "current",
                )
        for index, name in enumerate(["Demo Reception", "Demo Trainer"], 1):
            user, created = self.account(f"staff-{index}", f"+8801888{index:06d}", name, "admin")
            if created:
                StaffProfile.objects.create(user=user, short_id=next_display("staff"))
                self.activity(
                    f"staff-{index}",
                    "staff",
                    "create",
                    "adminActivityStaffCreated",
                    {"name": name, "short_id": user.staff_profile.short_id},
                )
        for index in range(1, count + 1):
            self.seed_member(index, plans)
        for index in range(12):
            category = ["rent", "utilities", "salary", "equipment", "other"][index % 5]
            day = self.today - timedelta(days=index * 7)
            title = f"Demo {category} {index + 1}"
            _, created = self.put(
                Cost,
                index,
                title=title,
                category=category,
                amount_taka=1500 + index * 500,
                date=day,
                note="Synthetic demo expense",
                created_by=self.actor,
            )
            if created:
                self.activity(
                    f"cost-{index}",
                    "cost",
                    "create",
                    "adminActivityCostCreated",
                    {"title": title},
                    day,
                )
        for offset in [7, 30]:
            day = self.today + timedelta(days=offset)
            if not Holiday.objects.filter(date=day).exists():
                self.put(Holiday, offset, date=day, name="Demo gym holiday")

    def seed_member(self, index, plans):
        phone = f"+8801999{index:06d}"
        names = [
            "Abir Hasan",
            "Nusrat Jahan",
            "Rafiq Ahmed",
            "Farhana Akter",
            "Sajid Rahman",
            "Mim Chowdhury",
            "Tanvir Islam",
            "Samira Khan",
            "Imran Hossain",
            "Nadia Sultana",
        ]
        user, created = self.account(
            f"member-{index}", phone, "Demo " + names[(index - 1) % len(names)], "member"
        )
        self.member_phones.append(user.phone_e164)
        if not created:
            return
        state = (index - 1) % 6
        profile = MemberProfile.objects.create(
            id=demo_id("memberprofile", index),
            user=user,
            member_id=next_display("member"),
            emergency_name="Demo Emergency Contact",
            emergency_relationship="parent",
            emergency_phone_e164="+8801777000000",
            blood_group=["A+", "B+", "O+", "Unknown"][index % 4],
            profile_complete=True,
        )
        self.counts["member profiles"] += 1
        joined = self.today - timedelta(days=75 if state >= 2 else index % 10)
        User.objects.filter(pk=user.pk).update(created_at=self.at(joined))
        MemberProfile.objects.filter(pk=profile.pk).update(created_at=self.at(joined))
        if state < 2:
            return
        expired = state == 5
        plan = plans[0] if expired else plans[index % len(plans)]
        first_day = self.today - timedelta(days=75 if plan.duration_months == 1 else 50)
        intervals = []
        days = [first_day]
        if not expired and plan.duration_months == 1:
            days.append(self.today - timedelta(days=12))
        for payment_index, day in enumerate(days):
            self.seed_payment(profile, plan, index, payment_index, day)
            intervals.append((day, go_add_months(day, plan.duration_months)))
        profile.plan = plan
        profile.expires_on = intervals[-1][1]
        profile.membership_status = "expired" if expired else "active"
        profile.fingerprint_status = "pending" if index % 4 == 0 else "ready"
        profile.save()
        for offset in range(90):
            day = self.today - timedelta(days=offset)
            if (
                day.weekday() == 4
                or (offset + index) % 3
                or not any(start <= day <= end for start, end in intervals)
            ):
                continue
            self.put(
                CheckIn,
                f"{index}-{day}",
                member=profile,
                checked_in_at=self.at(day),
                check_in_date=day,
                source="device",
            )

    def seed_payment(self, member, plan, index, payment_index, day):
        first = payment_index == 0
        channel = "cash" if (index + payment_index) % 2 else "sslcommerz"
        kind = (
            ("first_payment" if first else "renewal")
            if channel == "cash"
            else ("first_purchase" if first else "renew")
        )
        amounts = pricing(plan, day)
        renewal = amounts["effective_renewal_taka"]
        total = amounts["effective_first_payment_taka"] if first else renewal
        lines = [{"label": "Period coverage", "amount_taka": renewal}]
        if total > renewal:
            lines.insert(0, {"label": "Admission fee", "amount_taka": total - renewal})
        key = f"{index}-{payment_index}"
        tran_id = "DEMO" + demo_id("transaction", key).hex[:24] if channel == "sslcommerz" else None
        payment, _ = self.put(
            Payment,
            key,
            member=member,
            plan=plan,
            catalog_id=plan.catalog_id,
            channel=channel,
            kind=kind,
            is_first_payment=first,
            amount_taka=total,
            status="paid",
            paid_at=self.at(day),
            line_items=lines,
            tran_id=tran_id,
        )
        Payment.objects.filter(pk=payment.pk).update(created_at=self.at(day))
        if tran_id:
            session, _ = self.put(
                PaymentSession,
                key,
                member=member,
                plan=plan,
                kind=kind,
                tran_id=tran_id,
                amount_taka=total,
                status="paid",
                paid_at=self.at(day),
                pricing_snapshot={
                    "amount_taka": total,
                    "line_items": lines,
                    "duration_months": plan.duration_months,
                    "catalog_id": plan.catalog_id,
                },
            )
            PaymentSession.objects.filter(pk=session.pk).update(created_at=self.at(day))
        self.activity(
            f"payment-{key}",
            "member",
            "activate" if first else "update",
            ("adminActivityMemberCashActivated" if first else "adminActivityMemberCashRenewed")
            if channel == "cash"
            else "adminActivityMemberDemoPaid",
            {
                "member_id": member.member_id,
                "name": member.user.full_name,
                "amount": format_taka(total),
                "plan": plan.name,
            },
            day,
        )
