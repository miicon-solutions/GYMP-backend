from decimal import Decimal

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from accounts.models import User
from fitness.models import FitnessProfile
from nutrition.models import Recipe
from workouts.models import Exercise, Routine

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def seed_data(db):
    call_command("seed_fitness_data")


@pytest.fixture
def auth_user(db):
    user = User.objects.create_user(
        "+8801700000001", role="member", email="athlete@example.com", full_name="Pro Athlete"
    )
    user.set_password("SecurePassword123!")
    user.save()
    FitnessProfile.objects.create(
        user=user,
        experience_level="advanced",
        preferred_units="metric",
        daily_calorie_target=2800,
        daily_water_target_ml=4000,
        protein_target_g=180,
        carbs_target_g=300,
        fat_target_g=80,
    )
    return user


@pytest.fixture
def auth_client(auth_user):
    client = APIClient()
    client.force_authenticate(user=auth_user)
    return client


@pytest.fixture
def staff_user(db):
    user = User.objects.create_superuser(
        "+8801700000002", password="StaffPassword123!", email="staff@example.com", full_name="Gym Staff"
    )
    return user


@pytest.fixture
def staff_client(staff_user):
    client = APIClient()
    client.force_authenticate(user=staff_user)
    return client


# =========================================================================
# 1. AUTH & PROFILE / ANTHROPOMETRY
# =========================================================================


def test_auth_register_and_login(client):
    reg_payload = {
        "email": "newbie@example.com",
        "password": "StrongPassword999!",
        "full_name": "Newbie Lifter",
    }
    resp = client.post("/api/auth/register/", reg_payload, format="json")
    assert resp.status_code == 201
    assert "access_token" in resp.data
    assert "refresh_token" in resp.data

    user = User.objects.get(email="newbie@example.com")
    assert user.full_name == "Newbie Lifter"
    assert FitnessProfile.objects.filter(user=user).exists()

    # Login with email and password
    login_payload = {
        "email": "newbie@example.com",
        "password": "StrongPassword999!",
    }
    resp = client.post("/api/auth/login/", login_payload, format="json")
    assert resp.status_code == 200
    assert "access_token" in resp.data


def test_user_profile_get_and_patch(auth_client, auth_user):
    resp = auth_client.get("/api/users/profile/")
    assert resp.status_code == 200
    assert resp.data["experience_level"] == "advanced"
    assert resp.data["daily_calorie_target"] == 2800

    update_payload = {
        "daily_calorie_target": 3000,
        "protein_target_g": 200,
        "preferred_units": "imperial",
    }
    resp = auth_client.patch("/api/users/profile/", update_payload, format="json")
    assert resp.status_code == 200
    assert resp.data["daily_calorie_target"] == 3000
    assert resp.data["protein_target_g"] == 200
    assert resp.data["preferred_units"] == "imperial"


def test_anthropometry_logging_and_listing(auth_client, auth_user):
    payload = {
        "weight": "82.50",
        "weight_unit": "kg",
        "body_fat_percentage": "14.2",
        "waist_inches": "32.50",
    }
    resp = auth_client.post("/api/users/anthropometry/", payload, format="json")
    assert resp.status_code == 201
    assert Decimal(resp.data["weight"]) == Decimal("82.50")
    assert Decimal(resp.data["body_fat_percentage"]) == Decimal("14.2")

    resp = auth_client.get("/api/users/anthropometry/")
    assert resp.status_code == 200
    assert len(resp.data["results"]) >= 1


# =========================================================================
# 2. WORKOUTS, SETS, 1RM, PR & ANALYTICS
# =========================================================================


def test_exercises_filtering_and_custom_creation(auth_client, auth_user):
    # Filter predefined exercises
    resp = auth_client.get("/api/workouts/exercises/?muscle_group=chest")
    assert resp.status_code == 200
    names = [e["name"] for e in resp.data["results"]]
    assert "Barbell Bench Press" in names

    # Search
    resp = auth_client.get("/api/workouts/exercises/?search=Squat")
    assert resp.status_code == 200
    assert any("Squat" in e["name"] for e in resp.data["results"])

    # Create custom exercise
    custom_payload = {
        "name": "Bulgarian Split Squat",
        "muscle_group": "quads",
        "category": "dumbbell",
        "target_vector": "Quadriceps & Glute Medius",
        "muscle_distribution": {"Quadriceps": 60, "Gluteus": 40},
    }
    resp = auth_client.post("/api/workouts/exercises/", custom_payload, format="json")
    assert resp.status_code == 201
    assert resp.data["is_custom"] is True
    assert resp.data["slug"] == "bulgarian-split-squat"


def test_workout_session_lifecycle_and_pr_analytics(auth_client, auth_user):
    bench = Exercise.objects.get(slug="barbell-bench-press")
    routine = Routine.objects.filter(is_predefined=True).first()

    # 1. Start workout session
    resp = auth_client.post(
        "/api/workouts/sessions/start/",
        {"routine_id": str(routine.id), "title": "Heavy Chest Day"},
        format="json",
    )
    assert resp.status_code == 201
    session_id = resp.data["id"]
    assert resp.data["status"] == "in_progress"

    # Cannot start a second concurrent session
    resp_conflict = auth_client.post(
        "/api/workouts/sessions/start/",
        {"title": "Another Session"},
        format="json",
    )
    assert resp_conflict.status_code == 409

    # 2. Log Warmup set (100 kg x 10 reps -> 220.46 lbs x 10)
    resp = auth_client.post(
        f"/api/workouts/sessions/{session_id}/log-set/",
        {
            "exercise_id": str(bench.id),
            "set_type": "warmup",
            "weight": "60.00",
            "weight_unit": "kg",
            "reps": 10,
            "rpe": "6.0",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["set"]["set_type"] == "warmup"
    assert resp.data["set"]["is_pr"] is False

    # 3. Log Working Set 1: 100 kg x 5 reps -> epley 1rm = weight * (1 + 5/30) = 100 * 1.1667
    resp = auth_client.post(
        f"/api/workouts/sessions/{session_id}/log-set/",
        {
            "exercise_id": str(bench.id),
            "set_type": "working",
            "weight": "100.00",
            "weight_unit": "kg",
            "reps": 5,
            "rpe": "8.5",
        },
        format="json",
    )
    assert resp.status_code == 201
    calc_1rm = Decimal(resp.data["set"]["calculated_1rm"])
    assert calc_1rm > Decimal("250.00")  # in lbs: ~257.21 lbs

    # 4. Complete session
    resp = auth_client.post(
        f"/api/workouts/sessions/{session_id}/complete/",
        {"notes": "Great pressing feeling."},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["status"] == "completed"
    assert Decimal(resp.data["total_volume_lbs"]) > Decimal("1000")

    # 5. Check Exercise Analytics
    analytics_resp = auth_client.get(f"/api/workouts/analytics/exercise/{bench.id}/?timeframe=3m")
    assert analytics_resp.status_code == 200
    adata = analytics_resp.data
    assert adata["exercise"]["name"] == "Barbell Bench Press"
    assert len(adata["chart_data"]) >= 1
    assert adata["lifetime_pr"]["estimated_1rm"] is not None
    assert Decimal(adata["total_volume_lbs"]) > 0
    assert len(adata["volume_by_muscle_group"]) >= 1


# =========================================================================
# 3. SCHEDULES & PERIODIZATION
# =========================================================================


def test_schedules_active_cycle_and_autopopulate(auth_client, auth_user):
    # Auto-populate or create active cycle
    cycle_payload = {
        "name": "PPLRPPL 7-Day Microcycle",
        "mesocycle_phase": "Mesocycle Phase II - Progressive Overload",
        "cycle_length_days": 7,
    }
    resp = auth_client.post("/api/schedules/active-cycle/", cycle_payload, format="json")
    assert resp.status_code == 201
    assert len(resp.data["days"]) == 7

    # Auto-populate using PPL split template
    resp = auth_client.post(
        "/api/schedules/active-cycle/auto-populate/",
        {"template": "ppl", "prefer_custom": False},
        format="json",
    )
    assert resp.status_code == 200
    days = resp.data["days"]
    assert days[0]["is_rest_day"] is False
    assert days[0]["assigned_routine"] is not None
    assert days[3]["is_rest_day"] is True  # Day 4 is Rest in PPLRPPL

    # Update/Swap day 0
    resp = auth_client.put(
        "/api/schedules/active-cycle/days/0/",
        {"label": "Chest Power Morning", "is_rest_day": False},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["days"][0]["label"] == "Chest Power Morning"


# =========================================================================
# 4. NUTRITION & HYDRATION
# =========================================================================


def test_nutrition_recipes_meal_logging_and_hydration(auth_client, auth_user):
    # 1. List recipes with tag filter
    resp = auth_client.get("/api/nutrition/recipes/?tag=High Protein")
    assert resp.status_code == 200
    assert len(resp.data["results"]) >= 1

    recipe = Recipe.objects.get(title="Crispy Lemon Herb Chicken Breast & Jasmine Rice")
    variation = recipe.cooking_variations.get(variation_name="Air Fryer Mode")

    # 2. Retrieve recipe detail with variations
    resp = auth_client.get(f"/api/nutrition/recipes/{recipe.id}/")
    assert resp.status_code == 200
    assert len(resp.data["cooking_variations"]) == 2

    # 3. Log a meal using recipe + variation (+35 kcal offset)
    resp = auth_client.post(
        "/api/nutrition/logs/today/",
        {
            "meal_slot": "lunch",
            "recipe_id": str(recipe.id),
            "selected_variation_id": str(variation.id),
            "status": "planned",
        },
        format="json",
    )
    assert resp.status_code == 201
    meal_id = resp.data["id"]
    # Base 520 + 35 offset = 555 kcal
    assert Decimal(resp.data["calories"]) == Decimal("555.00")
    assert resp.data["status"] == "planned"

    # 4. Confirm intake
    resp = auth_client.patch(f"/api/nutrition/logs/{meal_id}/confirm-intake/", format="json")
    assert resp.status_code == 200
    assert resp.data["status"] == "consumed"

    # 5. Check daily nutrition summary
    resp = auth_client.get("/api/nutrition/logs/today/")
    assert resp.status_code == 200
    assert Decimal(resp.data["consumed"]["calories"]) == Decimal("555.00")
    assert Decimal(resp.data["targets"]["calories"]) == Decimal("2800.00")

    # 6. Hydration Quick-Add (+500ml)
    resp = auth_client.post(
        "/api/nutrition/hydration/quick-add/", {"amount_ml": 500}, format="json"
    )
    assert resp.status_code == 201
    assert resp.data["total_intake_ml"] == 500
    assert resp.data["target_intake_ml"] == 4000
    # 500 / 4000 = 12.5%
    assert Decimal(resp.data["quota_progress_percentage"]) == Decimal("12.5")

    # 7. Check today's hydration
    resp = auth_client.get("/api/nutrition/hydration/today/")
    assert resp.status_code == 200
    assert resp.data["total_intake_ml"] == 500

    # 8. Custom Fuel Synthesizer
    synth_payload = {
        "title": "Protein Oat Bomb",
        "calories": "650.00",
        "protein_g": "48.00",
        "carbs_g": "75.00",
        "fat_g": "16.00",
        "ingredients": [
            {"name": "Rolled Oats", "amount": "80g", "calories": 300},
            {"name": "Whey Isolate", "amount": "40g", "calories": 150},
            {"name": "Almond Butter", "amount": "30g", "calories": 200},
        ],
        "instructions": ["Mix oats and whey with warm water", "Top with almond butter"],
        "tags": ["High Protein", "Breakfast"],
        "log_as_meal_today": True,
        "meal_slot": "breakfast",
    }
    resp = auth_client.post("/api/nutrition/custom-synthesizer/", synth_payload, format="json")
    assert resp.status_code == 201
    assert resp.data["title"] == "Protein Oat Bomb"
    assert resp.data["is_predefined"] is False


# =========================================================================
# 5. GYM JOURNAL & REFLECTION TELEMETRY
# =========================================================================


def test_gym_journal_workflow_and_tag_filtering(auth_client, auth_user):
    # 1. Get or initialize today's entry
    resp = auth_client.get("/api/journal/entries/today/")
    assert resp.status_code == 200
    entry_id = resp.data["id"]
    assert resp.data["energy_level"] == 3

    # 2. Update with subjective notes and cues via POST /api/journal/entries/today/
    update_payload = {
        "energy_level": 5,
        "muscle_soreness": 2,
        "sleep_hours": "8.5",
        "sleep_quality": "deep_rem",
        "cns_drive": "fired_up",
        "subjective_notes": "Smashed bench press #PR on 2nd working set! #LegDay tomorrow.",
        "protocol_adjustments": "Add 2.5kg to working weight next session.",
    }
    resp = auth_client.post("/api/journal/entries/today/", update_payload, format="json")
    assert resp.status_code == 200
    assert resp.data["energy_level"] == 5
    assert "#PR" in resp.data["tags"]
    assert "#LegDay" in resp.data["tags"]

    resp = auth_client.patch(f"/api/journal/entries/{entry_id}/", update_payload, format="json")
    assert resp.status_code == 200
    assert resp.data["energy_level"] == 5
    assert "#PR" in resp.data["tags"]
    assert "#LegDay" in resp.data["tags"]

    # 3. Filter by tag
    resp = auth_client.get("/api/journal/entries/?tag=PR")
    assert resp.status_code == 200
    assert len(resp.data["results"]) >= 1


# =========================================================================
# 6. STAFF PRIVILEGES: RECIPES, NUTRITION, WORKOUTS & SESSIONS
# =========================================================================


def test_staff_crud_recipe_nutrition_workouts_sessions(staff_client, auth_user, auth_client):
    # --- 1. RECIPES: Create, Edit, List, Delete by Staff ---
    recipe_payload = {
        "title": "Staff High-Performance Bowl",
        "base_calories": 520,
        "base_protein_g": 45,
        "base_carbs_g": 60,
        "base_fat_g": 12,
        "base_prep_time_minutes": 10,
        "base_cook_time_minutes": 15,
        "ingredients_json": [{"name": "Lean Beef", "amount": "200g"}],
        "instructions": ["Sear lean beef", "Add jasmine rice"],
        "tags": ["High Protein", "Staff Choice"],
        "cooking_variations": [
            {
                "variation_name": "Air Fryer Crisp",
                "cook_time_minutes": 12,
                "calorie_offset": 25,
            }
        ],
    }
    r_resp = staff_client.post("/api/v1/nutrition/recipes/", recipe_payload, format="json")
    assert r_resp.status_code == 201
    recipe_id = r_resp.data["id"]
    assert r_resp.data["is_predefined"] is True

    # Staff Edit Recipe
    r_edit = staff_client.patch(
        f"/api/v1/nutrition/recipes/{recipe_id}/",
        {"title": "Staff Supreme Performance Bowl", "base_calories": 550},
        format="json",
    )
    assert r_edit.status_code == 200
    assert r_edit.data["title"] == "Staff Supreme Performance Bowl"

    # Staff List Recipes (sees all)
    r_list = staff_client.get("/api/v1/nutrition/recipes/")
    assert r_list.status_code == 200
    assert any(r["id"] == recipe_id for r in r_list.data["results"])

    # Staff Delete Recipe
    r_del = staff_client.delete(f"/api/v1/nutrition/recipes/{recipe_id}/")
    assert r_del.status_code == 204

    # --- 2. WORKOUTS: Exercise & Routine CRUD by Staff ---
    # Staff creates system exercise
    ex_payload = {
        "name": "Staff Nordic Hamstring Curl",
        "muscle_group": "hamstrings",
        "category": "bodyweight",
        "target_vector": "Eccentric Knee Flexion",
        "youtube_links": [
            {"title": "Setup & Anchor Guide", "url": "https://www.youtube.com/watch?v=2C-uNgKwPLE"},
            {"title": "Eccentric Progression", "url": "https://youtu.be/hChjLQm68JE"},
        ],
    }
    ex_resp = staff_client.post("/api/v1/workouts/exercises/", ex_payload, format="json")
    assert ex_resp.status_code == 201
    ex_id = ex_resp.data["id"]
    assert ex_resp.data["is_custom"] is False
    assert len(ex_resp.data["youtube_links"]) == 2
    assert ex_resp.data["youtube_links"][0]["title"] == "Setup & Anchor Guide"

    # Member can view exercise and see the youtube links
    member_ex = auth_client.get(f"/api/v1/workouts/exercises/{ex_id}/")
    assert member_ex.status_code == 200
    assert len(member_ex.data["youtube_links"]) == 2

    # Staff edits exercise (updates vector and youtube links)
    ex_edit = staff_client.patch(
        f"/api/v1/workouts/exercises/{ex_id}/",
        {
            "target_vector": "Elite Knee Flexion Progression",
            "youtube_links": [
                {"title": "Setup & Anchor Guide", "url": "https://www.youtube.com/watch?v=2C-uNgKwPLE"},
                {"title": "Full ROM Tutorial", "url": "https://www.youtube.com/watch?v=example3"},
            ],
        },
        format="json",
    )
    assert ex_edit.status_code == 200
    assert ex_edit.data["target_vector"] == "Elite Knee Flexion Progression"
    assert len(ex_edit.data["youtube_links"]) == 2
    assert ex_edit.data["youtube_links"][1]["title"] == "Full ROM Tutorial"

    # Staff creates predefined routine
    routine_payload = {
        "title": "Staff Athletic Hypertrophy Routine",
        "estimated_duration_minutes": 55,
        "split_category": "lower",
        "focus_tag": "hypertrophy",
        "description": "Engineered by coaching staff.",
        "items": [
            {
                "exercise_id": ex_id,
                "order": 1,
                "target_sets": 4,
                "target_reps_range": "6-8",
                "rest_protocol_seconds": 90,
            }
        ],
    }
    rt_resp = staff_client.post("/api/v1/workouts/routines/", routine_payload, format="json")
    assert rt_resp.status_code == 201
    routine_id = rt_resp.data["id"]
    assert rt_resp.data["is_predefined"] is True

    # Staff edits routine
    rt_edit = staff_client.patch(
        f"/api/v1/workouts/routines/{routine_id}/",
        {"title": "Staff Championship Lower Body"},
        format="json",
    )
    assert rt_edit.status_code == 200
    assert rt_edit.data["title"] == "Staff Championship Lower Body"

    # Staff deletes routine
    rt_del = staff_client.delete(f"/api/v1/workouts/routines/{routine_id}/")
    assert rt_del.status_code == 204

    # Staff deletes exercise
    ex_del = staff_client.delete(f"/api/v1/workouts/exercises/{ex_id}/")
    assert ex_del.status_code == 204

    # --- 3. SESSIONS: Staff Start, Log Set, Edit, Complete, Delete Session ---
    # Staff starts session on behalf of member
    bench = Exercise.objects.get(name="Barbell Bench Press")
    start_resp = staff_client.post(
        "/api/v1/workouts/sessions/start/",
        {"user_id": str(auth_user.id), "title": "Staff Supervised Bench Session"},
        format="json",
    )
    assert start_resp.status_code == 201
    session_id = start_resp.data["id"]

    # Staff logs set on session
    set_resp = staff_client.post(
        f"/api/v1/workouts/sessions/{session_id}/log-set/",
        {"exercise_id": str(bench.id), "weight": "225", "reps": 5, "rpe": 8.5},
        format="json",
    )
    assert set_resp.status_code == 201

    # Staff edits session notes
    sess_edit = staff_client.patch(
        f"/api/v1/workouts/sessions/{session_id}/",
        {"notes": "Coached form adjustment on elbows."},
        format="json",
    )
    assert sess_edit.status_code == 200
    assert sess_edit.data["notes"] == "Coached form adjustment on elbows."

    # Staff completes session
    comp_resp = staff_client.post(
        f"/api/v1/workouts/sessions/{session_id}/complete/",
        {"notes": "Session completed with strict cadence."},
        format="json",
    )
    assert comp_resp.status_code == 200
    assert comp_resp.data["status"] == "completed"

    # Staff sees all sessions
    sess_list = staff_client.get(f"/api/v1/workouts/sessions/?user_id={auth_user.id}")
    assert sess_list.status_code == 200
    assert any(s["id"] == session_id for s in sess_list.data["results"])

    # Staff deletes session
    sess_del = staff_client.delete(f"/api/v1/workouts/sessions/{session_id}/")
    assert sess_del.status_code == 204

    # --- 4. NUTRITION: Staff Log Meal, Edit Meal, Edit Targets, Delete Meal ---
    # Staff views member's daily nutrition
    nutr_today = staff_client.get(f"/api/v1/nutrition/logs/today/?user_id={auth_user.id}")
    assert nutr_today.status_code == 200

    # Staff logs meal for member
    meal_resp = staff_client.post(
        "/api/v1/nutrition/logs/today/",
        {
            "user_id": str(auth_user.id),
            "custom_name": "Staff Prescribed Recovery Shake",
            "meal_slot": "workout",
            "calories": 420,
            "protein_g": 50,
            "carbs_g": 40,
            "fat_g": 5,
        },
        format="json",
    )
    assert meal_resp.status_code == 201
    meal_id = meal_resp.data["id"]

    # Staff edits meal log
    meal_edit = staff_client.patch(
        f"/api/v1/nutrition/logs/{meal_id}/",
        {"custom_name": "Staff Upgraded Recovery Shake", "calories": 460},
        format="json",
    )
    assert meal_edit.status_code == 200
    assert meal_edit.data["custom_name"] == "Staff Upgraded Recovery Shake"

    # Staff deletes meal log
    meal_del = staff_client.delete(f"/api/v1/nutrition/logs/{meal_id}/")
    assert meal_del.status_code == 204

    # Staff edits member's fitness/nutrition targets
    target_resp = staff_client.patch(
        f"/api/v1/users/profile/?user_id={auth_user.id}",
        {"daily_calorie_target": 3200, "protein_target_g": 200},
        format="json",
    )
    assert target_resp.status_code == 200
    assert target_resp.data["daily_calorie_target"] == 3200
    assert target_resp.data["protein_target_g"] == 200


def test_feed_articles_crud_and_saving(staff_client, auth_user, auth_client):
    # Member cannot publish article
    forbidden = auth_client.post(
        "/api/v1/feed/articles/",
        {
            "title": "Unauthorized Article",
            "url": "https://example.com/test",
            "category": "training",
        },
        format="json",
    )
    assert forbidden.status_code == 403

    # Staff publishes article
    pub_resp = staff_client.post(
        "/api/v1/feed/articles/",
        {
            "title": "Hypertrophy Volume Landmarks",
            "url": "https://rpstrength.com/volume-guide",
            "excerpt": "Comprehensive guide on MEV, MAV, and MRV per muscle group.",
            "source": "Renaissance Periodization",
            "category": "training",
            "tags": ["Hypertrophy", "Volume", "RP"],
            "reading_time_minutes": 8,
            "is_pinned": True,
        },
        format="json",
    )
    assert pub_resp.status_code == 201
    article_id = pub_resp.data["id"]

    # Member lists articles
    list_resp = auth_client.get("/api/v1/feed/articles/")
    assert list_resp.status_code == 200
    results = (
        list_resp.data["results"]
        if isinstance(list_resp.data, dict) and "results" in list_resp.data
        else list_resp.data
    )
    assert any(a["id"] == article_id for a in results)

    # Member saves article
    save_resp = auth_client.post(f"/api/v1/feed/articles/{article_id}/save/")
    assert save_resp.status_code == 200
    assert save_resp.data["is_saved"] is True

    # Member retrieves article - is_saved is True
    detail_resp = auth_client.get(f"/api/v1/feed/articles/{article_id}/")
    assert detail_resp.status_code == 200
    assert detail_resp.data["is_saved"] is True

    # Filter by saved_only=true
    saved_only_resp = auth_client.get("/api/v1/feed/articles/?saved_only=true")
    assert saved_only_resp.status_code == 200
    saved_results = (
        saved_only_resp.data["results"]
        if isinstance(saved_only_resp.data, dict) and "results" in saved_only_resp.data
        else saved_only_resp.data
    )
    assert any(a["id"] == article_id for a in saved_results)

    # Member unsaves article
    unsave_resp = auth_client.post(f"/api/v1/feed/articles/{article_id}/unsave/")
    assert unsave_resp.status_code == 200
    assert unsave_resp.data["is_saved"] is False

    # Staff edits article
    edit_resp = staff_client.patch(
        f"/api/v1/feed/articles/{article_id}/",
        {"title": "Hypertrophy Volume Landmarks 2.0", "reading_time_minutes": 10},
        format="json",
    )
    assert edit_resp.status_code == 200
    assert edit_resp.data["title"] == "Hypertrophy Volume Landmarks 2.0"

    # Staff deletes article
    del_resp = staff_client.delete(f"/api/v1/feed/articles/{article_id}/")
    assert del_resp.status_code == 204


# =========================================================================
# 7. TEST REPORT FIXES: TIMED/CARDIO EXERCISES, OVERALL ANALYTICS,
#    POST-WORKOUT SUMMARY, BODY DATA SYNC, CUSTOM SCHEDULE DAYS,
#    NUTRITION SUGGESTIONS & WARNINGS, ATTENDANCE TIME & MOTIVATION AVATAR
# =========================================================================


def test_timed_and_cardio_exercises_overall_analytics_and_workout_summary(auth_client, auth_user):
    # Sync body data first (Suggestion 6)
    prof_resp = auth_client.patch(
        "/api/v1/users/profile/",
        {"height_cm": "175.0", "weight_kg": "78.00", "age": 26, "sex": "male"},
        format="json",
    )
    assert prof_resp.status_code == 200
    assert Decimal(prof_resp.data["weight_kg"]) == Decimal("78.00")

    plank = Exercise.objects.get(slug="plank-hold")
    running = Exercise.objects.get(slug="treadmill-running")
    bench = Exercise.objects.get(slug="barbell-bench-press")
    assert plank.tracking_type == "time"
    assert running.tracking_type == "cardio"
    assert bench.tracking_type == "reps"

    # Session 1 (Baseline)
    s1 = auth_client.post(
        "/api/v1/workouts/sessions/start/",
        {"title": "Full Conditioning & Strength"},
        format="json",
    ).data["id"]
    auth_client.post(
        f"/api/v1/workouts/sessions/{s1}/log-set/",
        {"exercise_id": str(bench.id), "weight": "80.00", "weight_unit": "kg", "reps": 8},
        format="json",
    )
    auth_client.post(
        f"/api/v1/workouts/sessions/{s1}/log-set/",
        {"exercise_id": str(plank.id), "duration_minutes": 1, "duration_seconds": 30},
        format="json",
    )
    auth_client.post(
        f"/api/v1/workouts/sessions/{s1}/log-set/",
        {
            "exercise_id": str(running.id),
            "duration_minutes": 20,
            "duration_seconds": 0,
            "distance_km": "3.50",
        },
        format="json",
    )
    c1 = auth_client.post(f"/api/v1/workouts/sessions/{s1}/complete/", {}, format="json")
    assert c1.status_code == 200
    assert c1.data["estimated_calories_burned"] > 0

    # Session 2 (Improved weight, plank time, and running distance)
    s2 = auth_client.post(
        "/api/v1/workouts/sessions/start/",
        {"title": "Full Conditioning & Strength"},
        format="json",
    ).data["id"]
    set_bench = auth_client.post(
        f"/api/v1/workouts/sessions/{s2}/log-set/",
        {"exercise_id": str(bench.id), "weight": "85.00", "weight_unit": "kg", "reps": 10},
        format="json",
    )
    assert set_bench.status_code == 201
    assert Decimal(set_bench.data["set"]["weight_kg"]) == Decimal("85.00")

    set_plank = auth_client.post(
        f"/api/v1/workouts/sessions/{s2}/log-set/",
        {"exercise_id": str(plank.id), "duration_minutes": 2, "duration_seconds": 0},
        format="json",
    )
    assert set_plank.status_code == 201
    assert set_plank.data["set"]["duration_seconds"] == 120

    set_run = auth_client.post(
        f"/api/v1/workouts/sessions/{s2}/log-set/",
        {
            "exercise_id": str(running.id),
            "duration_minutes": 25,
            "duration_seconds": 30,
            "distance_km": "5.00",
        },
        format="json",
    )
    assert set_run.status_code == 201
    assert set_run.data["set"]["duration_seconds"] == 1530
    assert Decimal(set_run.data["set"]["distance_km"]) == Decimal("5.00")

    c2 = auth_client.post(f"/api/v1/workouts/sessions/{s2}/complete/", {}, format="json")
    assert c2.status_code == 200
    summary = c2.data["summary"]
    assert summary["is_calorie_estimate"] is True
    assert summary["estimated_calories_burned"] > 50
    assert summary["default_comparison_mode"] == "last_session"

    last_cmp = summary["comparisons"]["last_session"]
    assert last_cmp["has_baseline"] is True
    assert last_cmp["volume_kg"]["status"] == "improved"
    ex_statuses = {e["exercise_name"]: e["overall_status"] for e in last_cmp["exercises"]}
    assert ex_statuses["Barbell Bench Press"] == "improved"
    assert ex_statuses["Plank Hold"] == "improved"
    assert ex_statuses["Treadmill Running"] == "improved"

    # Overall analytics ("All workouts" option - Suggestion 3)
    overall = auth_client.get("/api/v1/workouts/analytics/overall/?timeframe=year")
    assert overall.status_code == 200
    assert overall.data["exercise"]["slug"] == "all-workouts"
    assert overall.data["unit"] == "kg"
    assert Decimal(overall.data["total_volume_kg"]) > 0
    assert overall.data["session_count"] >= 2


def test_custom_schedule_day_and_closed_day_note(auth_client, auth_user):
    from operations.services import seed_hours

    seed_hours()
    bench = Exercise.objects.get(slug="barbell-bench-press")
    plank = Exercise.objects.get(slug="plank-hold")

    # Fetch active cycle (auto-initializes if needed) and check Friday closed note (Suggestion 8)
    cycle_resp = auth_client.get("/api/v1/schedules/active-cycle/")
    assert cycle_resp.status_code == 200
    friday_days = [d for d in cycle_resp.data["days"] if d["weekday"] == 5]
    assert len(friday_days) == 1
    assert friday_days[0]["is_gym_closed"] is True
    assert "Gym is closed today" in friday_days[0]["closed_note"]

    # Configure a Custom Day with lifting rep range + timed exercise (Suggestion 7)
    put_resp = auth_client.put(
        "/api/v1/schedules/active-cycle/days/4/",
        {
            "label": "Friday Home & Core Custom",
            "is_rest_day": False,
            "split_category": "push",
            "focus_tag": "hypertrophy",
            "custom_exercises": [
                {
                    "exercise_id": str(bench.id),
                    "target_sets": 3,
                    "target_reps_range": "8-12",
                    "rest_protocol_seconds": 90,
                },
                {
                    "exercise_id": str(plank.id),
                    "target_sets": 3,
                    "target_reps_range": "1m 30s",
                    "target_duration_seconds": 90,
                    "rest_protocol_seconds": 60,
                },
            ],
        },
        format="json",
    )
    assert put_resp.status_code == 200
    day4 = put_resp.data["days"][4]
    assert day4["label"] == "Friday Home & Core Custom"
    assert day4["is_rest_day"] is False
    assert len(day4["custom_exercises"]) == 2
    assert len(day4["assigned_routine"]["items"]) == 2
    assert day4["assigned_routine"]["items"][1]["target_duration_seconds"] == 90


def test_nutrition_suggested_targets_warnings_and_profile_weight_sync(client, member, profile_payload):
    client.force_authenticate(member)
    # 1. Complete registration with body data (Suggestion 6)
    reg = client.post(
        "/api/v1/member/profile/complete/",
        {
            **profile_payload,
            "height_cm": "172.0",
            "weight_kg": "75.00",
            "age": 25,
            "sex": "male",
        },
        format="json",
    )
    assert reg.status_code == 200
    assert Decimal(reg.data["weight_kg"]) == Decimal("75.00")

    # 2. Nutrition summary automatically uses synced profile data without re-entering (Suggestion 9)
    nutr = client.get("/api/v1/nutrition/logs/today/")
    assert nutr.status_code == 200
    sug_initial = nutr.data["suggested_targets"]
    assert sug_initial["has_body_data"] is True
    assert sug_initial["weight_kg"] == 75.0
    assert len(nutr.data["bangladeshi_foods"]) >= 10

    # 3. Switch goal to lose_weight and test safe minimum & >20% warning
    client.patch(
        "/api/v1/users/profile/",
        {"nutrition_goal": "lose_weight", "reset_to_suggested": True},
        format="json",
    )
    lose_prof = client.get("/api/v1/users/profile/").data
    assert lose_prof["daily_calorie_target"] >= lose_prof["suggested_targets"]["safe_minimum_calories"]

    # Set an unsafe low calorie target (>20% below suggestion) -> non-blocking warning
    warn_resp = client.patch(
        "/api/v1/users/profile/",
        {"daily_calorie_target": 1100},
        format="json",
    )
    assert warn_resp.status_code == 200
    assert any(w["field"] == "calories" and w["level"] == "low" for w in warn_resp.data["warnings"])

    # 4. Update weight in member profile -> suggested targets update automatically
    client.put(
        "/api/v1/member/profile/",
        {
            **profile_payload,
            "height_cm": "172.0",
            "weight_kg": "85.00",
            "age": 25,
            "sex": "male",
        },
        format="json",
    )
    nutr_after = client.get("/api/v1/nutrition/logs/today/").data
    assert nutr_after["suggested_targets"]["weight_kg"] == 85.0
    assert nutr_after["suggested_targets"]["calories"] > sug_initial["calories"] - 600


def test_attendance_time_spent_exit_scan_auto_cap_and_motivation_streak(
    client, member, staff, plan, profile_payload
):
    from datetime import timedelta

    from django.utils import timezone

    from operations.services import seed_hours
    from payments.services import receive_cash

    seed_hours()
    member.member_profile.profile_complete = True
    member.member_profile.save()
    receive_cash(staff, member.member_profile, plan.pk)

    # Check in and then scan on exit 75 minutes later (Suggestion 2)
    in_time = (timezone.now() - timedelta(minutes=75)).isoformat()
    out_time = timezone.now().isoformat()
    r_in = client.post(
        "/api/v1/internal/attendance/check-in/",
        {"member_id": member.member_profile.member_id, "checked_in_at": in_time},
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert r_in.status_code == 200

    r_out = client.post(
        "/api/v1/internal/attendance/check-out/",
        {"member_id": member.member_profile.member_id, "checked_out_at": out_time},
        format="json",
        HTTP_X_DEVICE_KEY="test-device-key",
    )
    assert r_out.status_code == 200
    assert r_out.data["exit_only_record"] is True
    assert 70 <= r_out.data["duration_minutes"] <= 80

    # Member views attendance time spent today, weekly hours, and motivation avatar (Suggestions 1 & 2)
    client.force_authenticate(member)
    att = client.get("/api/v1/member/attendance/")
    assert att.status_code == 200
    assert att.data["today_minutes"] >= 70
    assert att.data["week_minutes"] >= 70
    assert att.data["motivation"]["current_streak"] >= 1
    assert att.data["motivation"]["avatar_mood"] in ("on_fire", "proud")

    # Member manually corrects session time to 95 minutes
    adj = client.post(
        "/api/v1/member/attendance/session/",
        {"action": "adjust_duration", "duration_minutes": 95},
        format="json",
    )
    assert adj.status_code == 200
    assert adj.data["today_minutes"] == 95


