from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from nutrition.models import CookingVariation, Recipe
from workouts.models import Exercise, Routine, RoutineExercise


class Command(BaseCommand):
    help = "Seed initial predefined exercises, routines (PPL split), and recipes with cooking variations."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding predefined fitness exercises...")
        exercises_data = [
            # Chest
            {
                "name": "Barbell Bench Press",
                "muscle_group": "chest",
                "category": "barbell",
                "target_vector": "Pectoralis Major",
                "muscle_distribution": {
                    "Pectoralis Major": 60,
                    "Anterior Deltoid": 25,
                    "Triceps Brachii": 15,
                },
                "youtube_links": [
                    {
                        "title": "Bench Press Technique (Setup & Arch)",
                        "url": "https://www.youtube.com/watch?v=rT7DgCr-3pg",
                    },
                    {
                        "title": "Bar Path & Elbow Flare Explained",
                        "url": "https://www.youtube.com/watch?v=esQi683XR44",
                    },
                ],
            },
            {
                "name": "Incline Dumbbell Press",
                "muscle_group": "chest",
                "category": "dumbbell",
                "target_vector": "Clavicular Pectoralis",
                "muscle_distribution": {
                    "Clavicular Head": 65,
                    "Anterior Deltoid": 25,
                    "Triceps": 10,
                },
                "youtube_links": [
                    {
                        "title": "Incline Dumbbell Press Bench Angle & Form",
                        "url": "https://www.youtube.com/watch?v=8iPEnn-ltC8",
                    }
                ],
            },
            {
                "name": "Cable Chest Flyes",
                "muscle_group": "chest",
                "category": "cable",
                "target_vector": "Pectoralis Sternal",
                "muscle_distribution": {
                    "Pectoralis Major": 80,
                    "Anterior Deltoid": 20,
                },
                "youtube_links": [
                    {
                        "title": "Cable Chest Fly Execution & Sternal Path",
                        "url": "https://www.youtube.com/watch?v=Iwe6AmxVf7o",
                    }
                ],
            },
            {
                "name": "Push-Ups",
                "muscle_group": "chest",
                "category": "bodyweight",
                "target_vector": "Pectoralis Major",
                "muscle_distribution": {
                    "Pectoralis Major": 55,
                    "Triceps": 30,
                    "Core": 15,
                },
                "youtube_links": [
                    {
                        "title": "Perfect Push-Up Form & Scapular Motion",
                        "url": "https://www.youtube.com/watch?v=IODxDxX7oi4",
                    }
                ],
            },
            # Back
            {
                "name": "Conventional Deadlift",
                "muscle_group": "back",
                "category": "barbell",
                "target_vector": "Posterior Chain / Erector Spinae",
                "muscle_distribution": {
                    "Hamstrings & Glutes": 40,
                    "Erector Spinae": 35,
                    "Latissimus Dorsi": 25,
                },
                "youtube_links": [
                    {
                        "title": "Deadlift Setup & Hip Hinge Masterclass",
                        "url": "https://www.youtube.com/watch?v=AweC3UaM14o",
                    }
                ],
            },
            {
                "name": "Barbell Bent-Over Row",
                "muscle_group": "back",
                "category": "barbell",
                "target_vector": "Latissimus Dorsi / Rhomboids",
                "muscle_distribution": {"Latissimus Dorsi": 50, "Rhomboids": 30, "Biceps": 20},
                "youtube_links": [
                    {
                        "title": "Barbell Row Form (Back Thickness & Torso Angle)",
                        "url": "https://www.youtube.com/watch?v=FWJR5Ve8gkQ",
                    }
                ],
            },
            {
                "name": "Pull-Ups",
                "muscle_group": "back",
                "category": "bodyweight",
                "target_vector": "Latissimus Dorsi",
                "muscle_distribution": {
                    "Latissimus Dorsi": 65,
                    "Biceps Brachii": 25,
                    "Posterior Deltoid": 10,
                },
                "youtube_links": [
                    {
                        "title": "Proper Pull-Up Form & Shoulder Retraction",
                        "url": "https://www.youtube.com/watch?v=eGo4IYlbE5g",
                    }
                ],
            },
            {
                "name": "Lat Pulldown",
                "muscle_group": "back",
                "category": "cable",
                "target_vector": "Latissimus Dorsi",
                "muscle_distribution": {
                    "Latissimus Dorsi": 70,
                    "Biceps Brachii": 20,
                    "Rear Deltoids": 10,
                },
                "youtube_links": [
                    {
                        "title": "Lat Pulldown Execution & Grip Mechanics",
                        "url": "https://www.youtube.com/watch?v=CAwf7n6Luuc",
                    }
                ],
            },
            # Quads & Lower Push
            {
                "name": "Barbell Back Squat",
                "muscle_group": "quads",
                "category": "barbell",
                "target_vector": "Quadriceps Femoris",
                "muscle_distribution": {"Quadriceps": 55, "Gluteus Maximus": 30, "Hamstrings": 15},
                "youtube_links": [
                    {
                        "title": "Squat Depth, Stance & Mechanics",
                        "url": "https://www.youtube.com/watch?v=gcNh17Ckjgg",
                    },
                    {
                        "title": "Fixing Knee Cave & Hip Drive",
                        "url": "https://www.youtube.com/watch?v=bEv6CCg2BC8",
                    },
                ],
            },
            {
                "name": "Leg Press",
                "muscle_group": "quads",
                "category": "machine",
                "target_vector": "Quadriceps Femoris",
                "muscle_distribution": {"Quadriceps": 70, "Gluteus": 20, "Calves": 10},
                "youtube_links": [
                    {
                        "title": "Leg Press Foot Placement & Knee Safety",
                        "url": "https://www.youtube.com/watch?v=IZxyjW7MPJQ",
                    }
                ],
            },
            {
                "name": "Leg Extension",
                "muscle_group": "quads",
                "category": "machine",
                "target_vector": "Quadriceps Isolation",
                "muscle_distribution": {"Rectus Femoris": 50, "Vastus Lateralis": 50},
                "youtube_links": [
                    {
                        "title": "Quad Isolation on Leg Extension Machine",
                        "url": "https://www.youtube.com/watch?v=YyvSfVjQeL0",
                    }
                ],
            },
            # Hamstrings & Glutes
            {
                "name": "Romanian Deadlift",
                "muscle_group": "hamstrings",
                "category": "barbell",
                "target_vector": "Hamstrings & Glutes",
                "muscle_distribution": {"Hamstrings": 60, "Gluteus Maximus": 30, "Erectors": 10},
                "youtube_links": [
                    {
                        "title": "Romanian Deadlift (RDL) Form for Hamstrings & Glutes",
                        "url": "https://www.youtube.com/watch?v=JCXUYuzwNrM",
                    }
                ],
            },
            {
                "name": "Lying Leg Curl",
                "muscle_group": "hamstrings",
                "category": "machine",
                "target_vector": "Hamstrings Isolation",
                "muscle_distribution": {"Biceps Femoris": 70, "Semitendinosus": 30},
                "youtube_links": [
                    {
                        "title": "Lying Leg Curl Technique & Hip Control",
                        "url": "https://www.youtube.com/watch?v=1Tq3QdYUuHs",
                    }
                ],
            },
            # Calves
            {
                "name": "Standing Calf Raise",
                "muscle_group": "calves",
                "category": "machine",
                "target_vector": "Gastrocnemius & Soleus",
                "muscle_distribution": {"Gastrocnemius": 70, "Soleus": 30},
                "youtube_links": [
                    {
                        "title": "Standing Calf Raise Full Stretch & Pause Guide",
                        "url": "https://www.youtube.com/watch?v=-M4-G8p8fmc",
                    }
                ],
            },
            {
                "name": "Seated Calf Raise",
                "muscle_group": "calves",
                "category": "machine",
                "target_vector": "Soleus Isolation",
                "muscle_distribution": {"Soleus": 80, "Gastrocnemius": 20},
                "youtube_links": [
                    {
                        "title": "Seated Calf Raise Soleus Hypertrophy",
                        "url": "https://www.youtube.com/watch?v=JbyjNymZOt0",
                    }
                ],
            },
            # Shoulders
            {
                "name": "Overhead Press",
                "muscle_group": "shoulders",
                "category": "barbell",
                "target_vector": "Anterior & Lateral Deltoid",
                "muscle_distribution": {
                    "Anterior Deltoid": 60,
                    "Lateral Deltoid": 25,
                    "Triceps": 15,
                },
                "youtube_links": [
                    {
                        "title": "Military Overhead Press Form (Bar Path & Lockout)",
                        "url": "https://www.youtube.com/watch?v=2yjwXTZQDDI",
                    }
                ],
            },
            {
                "name": "Dumbbell Lateral Raise",
                "muscle_group": "shoulders",
                "category": "dumbbell",
                "target_vector": "Lateral Deltoid",
                "muscle_distribution": {"Lateral Deltoid": 85, "Upper Trapezius": 15},
                "youtube_links": [
                    {
                        "title": "Dumbbell Lateral Raise for Side Delts (No Traps)",
                        "url": "https://www.youtube.com/watch?v=3VcKaXpzqRo",
                    }
                ],
            },
            {
                "name": "Cable Face Pull",
                "muscle_group": "shoulders",
                "category": "cable",
                "target_vector": "Rear Deltoid & Rotator Cuff",
                "muscle_distribution": {"Posterior Deltoid": 60, "Infraspinatus": 25, "Trapezius": 15},
                "youtube_links": [
                    {
                        "title": "Cable Face Pull for Rotator Cuff & Rear Delts",
                        "url": "https://www.youtube.com/watch?v=rep-qVOkqgk",
                    }
                ],
            },
            # Arms
            {
                "name": "Barbell Bicep Curl",
                "muscle_group": "arms",
                "category": "barbell",
                "target_vector": "Biceps Brachii",
                "muscle_distribution": {"Biceps Brachii": 85, "Brachialis": 15},
                "youtube_links": [
                    {
                        "title": "Barbell Bicep Curl Strict Execution",
                        "url": "https://www.youtube.com/watch?v=kwG2ipFRgfo",
                    }
                ],
            },
            {
                "name": "Incline Dumbbell Curl",
                "muscle_group": "arms",
                "category": "dumbbell",
                "target_vector": "Biceps Long Head",
                "muscle_distribution": {"Biceps Long Head": 75, "Brachialis": 25},
                "youtube_links": [
                    {
                        "title": "Incline Dumbbell Curl Long Head Bicep Stretch",
                        "url": "https://www.youtube.com/watch?v=soxrZlIl35U",
                    }
                ],
            },
            {
                "name": "Tricep Rope Pushdown",
                "muscle_group": "arms",
                "category": "cable",
                "target_vector": "Triceps Lateral Head",
                "muscle_distribution": {"Triceps Lateral": 70, "Triceps Long": 30},
                "youtube_links": [
                    {
                        "title": "Tricep Pushdown Form (Lateral Head & Lockout)",
                        "url": "https://www.youtube.com/watch?v=vB5OHsJ3EME",
                    }
                ],
            },
            {
                "name": "Weighted Dips",
                "muscle_group": "arms",
                "category": "bodyweight",
                "target_vector": "Triceps & Lower Pecs",
                "muscle_distribution": {
                    "Triceps Brachii": 55,
                    "Pectoralis Major": 35,
                    "Anterior Deltoid": 10,
                },
                "youtube_links": [
                    {
                        "title": "Parallel Bar Dips (Chest vs Tricep Lean)",
                        "url": "https://www.youtube.com/watch?v=2z8JmcrW-As",
                    }
                ],
            },
            # Core
            {
                "name": "Plank Hold",
                "muscle_group": "core",
                "category": "bodyweight",
                "target_vector": "Transverse Abdominis & Core",
                "muscle_distribution": {"Transverse Abdominis": 60, "Rectus Abdominis": 40},
                "youtube_links": [
                    {
                        "title": "Perfect Plank Form & Abdominal Bracing",
                        "url": "https://www.youtube.com/watch?v=ASdvN_XEl_c",
                    }
                ],
            },
            {
                "name": "Hanging Leg Raise",
                "muscle_group": "core",
                "category": "bodyweight",
                "target_vector": "Rectus Abdominis & Hip Flexors",
                "muscle_distribution": {"Lower Rectus Abdominis": 70, "Hip Flexors": 30},
                "youtube_links": [
                    {
                        "title": "Hanging Leg Raise Pelvic Tilt Guide for Abs",
                        "url": "https://www.youtube.com/watch?v=jb_j4Gg803c",
                    }
                ],
            },
            # Cardio / Endurance / Functional
            {
                "name": "Rowing Machine Intervals",
                "muscle_group": "full_body",
                "category": "cardio",
                "target_vector": "Full Body Aerobic Conditioning",
                "muscle_distribution": {"Cardiovascular": 50, "Posterior Chain": 30, "Lats & Biceps": 20},
                "youtube_links": [
                    {
                        "title": "Rowing Ergometer Technique & Power Stroke",
                        "url": "https://www.youtube.com/watch?v=zQ82RYIFLN8",
                    }
                ],
            },
            {
                "name": "Assault Bike Sprints",
                "muscle_group": "full_body",
                "category": "cardio",
                "target_vector": "Maximal Anaerobic Power",
                "muscle_distribution": {"Cardiovascular": 60, "Quadriceps": 25, "Upper Body": 15},
                "youtube_links": [
                    {
                        "title": "Assault AirBike Sprints (Pacing & Arm Drive)",
                        "url": "https://www.youtube.com/watch?v=YfWJ2a-t71o",
                    }
                ],
            },
            {
                "name": "Kettlebell Swings",
                "muscle_group": "glutes",
                "category": "dumbbell",
                "target_vector": "Posterior Explosive Power",
                "muscle_distribution": {"Gluteus Maximus": 55, "Hamstrings": 30, "Cardiovascular": 15},
                "youtube_links": [
                    {
                        "title": "Kettlebell Swing Form (Hip Hinge Power)",
                        "url": "https://www.youtube.com/watch?v=YSxHifyI608",
                    }
                ],
            },
            {
                "name": "Jump Rope Conditioning",
                "muscle_group": "calves",
                "category": "cardio",
                "target_vector": "Footwork & Calf Endurance",
                "muscle_distribution": {"Cardiovascular": 50, "Calves": 50},
                "youtube_links": [
                    {
                        "title": "Jump Rope Footwork & Boxer Skip",
                        "url": "https://www.youtube.com/watch?v=u3zgHI8QnqE",
                    }
                ],
            },
            # Additional Chest Exercises
            {
                "name": "Decline Barbell Bench Press",
                "muscle_group": "chest",
                "category": "barbell",
                "target_vector": "Lower Pectoralis Major",
                "muscle_distribution": {"Pectoralis Major": 75, "Triceps": 20, "Anterior Deltoid": 5},
                "youtube_links": [
                    {"title": "Decline Bench Press Lower Chest Overload", "url": "https://www.youtube.com/watch?v=LfyQBUKR8SE"}
                ],
            },
            {
                "name": "Dumbbell Chest Flyes",
                "muscle_group": "chest",
                "category": "dumbbell",
                "target_vector": "Pectoralis Stretch Tension",
                "muscle_distribution": {"Pectoralis Major": 85, "Anterior Deltoid": 15},
                "youtube_links": [
                    {"title": "Dumbbell Chest Fly Form & Deep Pec Stretch", "url": "https://www.youtube.com/watch?v=eozdVDA78K0"}
                ],
            },
            {
                "name": "Machine Chest Press",
                "muscle_group": "chest",
                "category": "machine",
                "target_vector": "Mid Pectoralis Horizontal Drive",
                "muscle_distribution": {"Pectoralis Major": 70, "Triceps": 20, "Anterior Deltoid": 10},
                "youtube_links": [
                    {"title": "Seated Machine Chest Press Setup", "url": "https://www.youtube.com/watch?v=xUm0BiZCWlQ"}
                ],
            },
            {
                "name": "Low-to-High Cable Crossover",
                "muscle_group": "chest",
                "category": "cable",
                "target_vector": "Clavicular Pectoral Head",
                "muscle_distribution": {"Clavicular Head": 75, "Anterior Deltoid": 25},
                "youtube_links": [
                    {"title": "Low to High Cable Fly for Upper Chest", "url": "https://www.youtube.com/watch?v=bEb95Z_Z7O0"}
                ],
            },
            # Additional Back Exercises
            {
                "name": "T-Bar Row",
                "muscle_group": "back",
                "category": "barbell",
                "target_vector": "Mid-Back & Rhomboids",
                "muscle_distribution": {"Rhomboids": 40, "Latissimus Dorsi": 40, "Biceps": 20},
                "youtube_links": [
                    {"title": "T-Bar Row Form for Mid-Back Thickness", "url": "https://www.youtube.com/watch?v=j3Igk5nyZE4"}
                ],
            },
            {
                "name": "Seated Cable Row",
                "muscle_group": "back",
                "category": "cable",
                "target_vector": "Horizontal Lat & Scapular Drive",
                "muscle_distribution": {"Latissimus Dorsi": 50, "Rhomboids": 30, "Biceps": 20},
                "youtube_links": [
                    {"title": "Seated Cable Row Form & Scapular Squeeze", "url": "https://www.youtube.com/watch?v=GZbfZ033f74"}
                ],
            },
            {
                "name": "Single-Arm Dumbbell Row",
                "muscle_group": "back",
                "category": "dumbbell",
                "target_vector": "Unilateral Lat Overload",
                "muscle_distribution": {"Latissimus Dorsi": 65, "Biceps": 20, "Rear Deltoid": 15},
                "youtube_links": [
                    {"title": "One Arm Dumbbell Row Form (No Twisting)", "url": "https://www.youtube.com/watch?v=dFzUjzfih7k"}
                ],
            },
            {
                "name": "Straight-Arm Cable Pulldown",
                "muscle_group": "back",
                "category": "cable",
                "target_vector": "Latissimus Dorsi Isolation",
                "muscle_distribution": {"Latissimus Dorsi": 80, "Teres Major": 15, "Triceps Long Head": 5},
                "youtube_links": [
                    {"title": "Straight Arm Lat Pulldown Technique", "url": "https://www.youtube.com/watch?v=G_Tf_l_Xw_Y"}
                ],
            },
            # Additional Quad Exercises
            {
                "name": "Front Squat",
                "muscle_group": "quads",
                "category": "barbell",
                "target_vector": "Anterior Quadriceps & Core",
                "muscle_distribution": {"Quadriceps": 70, "Gluteus Maximus": 20, "Core": 10},
                "youtube_links": [
                    {"title": "Front Squat Grip & Upright Torso Guide", "url": "https://www.youtube.com/watch?v=uYumuL_G_V0"}
                ],
            },
            {
                "name": "Bulgarian Split Squat",
                "muscle_group": "quads",
                "category": "dumbbell",
                "target_vector": "Unilateral Quad & Glute Hypertrophy",
                "muscle_distribution": {"Quadriceps": 55, "Gluteus Maximus": 35, "Hamstrings": 10},
                "youtube_links": [
                    {"title": "Bulgarian Split Squat Form for Quads & Glutes", "url": "https://www.youtube.com/watch?v=2C-uNgKwPLE"}
                ],
            },
            {
                "name": "Hack Squat",
                "muscle_group": "quads",
                "category": "machine",
                "target_vector": "Deep Knee Flexion Quad Overload",
                "muscle_distribution": {"Vastus Lateralis": 50, "Rectus Femoris": 35, "Gluteus": 15},
                "youtube_links": [
                    {"title": "Machine Hack Squat Foot Placement & Depth", "url": "https://www.youtube.com/watch?v=0tn5K9NlCfo"}
                ],
            },
            {
                "name": "Goblet Squat",
                "muscle_group": "quads",
                "category": "dumbbell",
                "target_vector": "Beginner Squat Mechanics",
                "muscle_distribution": {"Quadriceps": 60, "Gluteus": 25, "Core": 15},
                "youtube_links": [
                    {"title": "Goblet Squat Form for Beginners", "url": "https://www.youtube.com/watch?v=MeIiIdhvXT4"}
                ],
            },
            # Additional Hamstrings & Glutes
            {
                "name": "Barbell Hip Thrust",
                "muscle_group": "glutes",
                "category": "barbell",
                "target_vector": "Gluteus Maximus Peak Contraction",
                "muscle_distribution": {"Gluteus Maximus": 80, "Hamstrings": 15, "Quadriceps": 5},
                "youtube_links": [
                    {"title": "Barbell Hip Thrust Technique & Bench Height", "url": "https://www.youtube.com/watch?v=SEdqd1n0cvg"}
                ],
            },
            {
                "name": "Seated Leg Curl",
                "muscle_group": "hamstrings",
                "category": "machine",
                "target_vector": "Hamstring Lengthened Hypertrophy",
                "muscle_distribution": {"Biceps Femoris": 65, "Semimembranosus": 35},
                "youtube_links": [
                    {"title": "Seated Leg Curl Hamstring Hypertrophy", "url": "https://www.youtube.com/watch?v=ELOCsoDSmrg"}
                ],
            },
            {
                "name": "Cable Glute Kickback",
                "muscle_group": "glutes",
                "category": "cable",
                "target_vector": "Gluteus Maximus Upper Division",
                "muscle_distribution": {"Gluteus Maximus": 85, "Hamstrings": 15},
                "youtube_links": [
                    {"title": "Cable Glute Kickbacks Form & Glute Max", "url": "https://www.youtube.com/watch?v=nl_Z1_sF1_Q"}
                ],
            },
            {
                "name": "Good Mornings",
                "muscle_group": "hamstrings",
                "category": "barbell",
                "target_vector": "Posterior Chain Hip Hinge",
                "muscle_distribution": {"Hamstrings": 50, "Erector Spinae": 35, "Gluteus": 15},
                "youtube_links": [
                    {"title": "Good Morning Exercise Hip Hinge Form", "url": "https://www.youtube.com/watch?v=YA-h3n9L4YU"}
                ],
            },
            # Additional Calves
            {
                "name": "Leg Press Calf Raise",
                "muscle_group": "calves",
                "category": "machine",
                "target_vector": "Straight-Leg Gastrocnemius Force",
                "muscle_distribution": {"Gastrocnemius": 75, "Soleus": 25},
                "youtube_links": [
                    {"title": "Leg Press Calf Raise Ankle Extension", "url": "https://www.youtube.com/watch?v=1SraI_3Z1_4"}
                ],
            },
            # Additional Shoulders
            {
                "name": "Arnold Press",
                "muscle_group": "shoulders",
                "category": "dumbbell",
                "target_vector": "Anterior & Lateral Rotation Press",
                "muscle_distribution": {"Anterior Deltoid": 50, "Lateral Deltoid": 35, "Triceps": 15},
                "youtube_links": [
                    {"title": "Arnold Dumbbell Press Rotation & Path", "url": "https://www.youtube.com/watch?v=6Z15_WdXmVw"}
                ],
            },
            {
                "name": "Reverse Pec Deck Fly",
                "muscle_group": "shoulders",
                "category": "machine",
                "target_vector": "Posterior Deltoid Isolation",
                "muscle_distribution": {"Posterior Deltoid": 80, "Rhomboids": 20},
                "youtube_links": [
                    {"title": "Reverse Pec Deck for Rear Delts", "url": "https://www.youtube.com/watch?v=5yMaQvU8_Wc"}
                ],
            },
            {
                "name": "Cable Lateral Raise",
                "muscle_group": "shoulders",
                "category": "cable",
                "target_vector": "Lateral Deltoid Constant Tension",
                "muscle_distribution": {"Lateral Deltoid": 90, "Trapezius": 10},
                "youtube_links": [
                    {"title": "Behind-the-Back Cable Lateral Raise", "url": "https://www.youtube.com/watch?v=PPrzBWZDOhA"}
                ],
            },
            # Additional Arms
            {
                "name": "Hammer Curls",
                "muscle_group": "arms",
                "category": "dumbbell",
                "target_vector": "Brachialis & Brachioradialis",
                "muscle_distribution": {"Brachialis": 60, "Brachioradialis": 25, "Biceps": 15},
                "youtube_links": [
                    {"title": "Dumbbell Hammer Curls for Brachialis", "url": "https://www.youtube.com/watch?v=zC3nLlEvin4"}
                ],
            },
            {
                "name": "Preacher Curl",
                "muscle_group": "arms",
                "category": "barbell",
                "target_vector": "Biceps Short Head Peak Tension",
                "muscle_distribution": {"Biceps Short Head": 80, "Brachialis": 20},
                "youtube_links": [
                    {"title": "EZ Bar Preacher Curl Short Head Isolation", "url": "https://www.youtube.com/watch?v=fIWP-FRFNU0"}
                ],
            },
            {
                "name": "Skull Crushers",
                "muscle_group": "arms",
                "category": "barbell",
                "target_vector": "Triceps Medial & Long Head",
                "muscle_distribution": {"Triceps Long Head": 60, "Triceps Medial": 40},
                "youtube_links": [
                    {"title": "Lying Triceps Extension Skull Crushers", "url": "https://www.youtube.com/watch?v=d_KZxkY_0cM"}
                ],
            },
            {
                "name": "Overhead Cable Tricep Extension",
                "muscle_group": "arms",
                "category": "cable",
                "target_vector": "Triceps Long Head Deep Stretch",
                "muscle_distribution": {"Triceps Long Head": 75, "Triceps Lateral": 25},
                "youtube_links": [
                    {"title": "Overhead Cable Triceps Extension Long Head", "url": "https://www.youtube.com/watch?v=ns-RGsbYeKA"}
                ],
            },
            # Additional Core
            {
                "name": "Ab Wheel Rollout",
                "muscle_group": "core",
                "category": "bodyweight",
                "target_vector": "Anterior Core Anti-Extension",
                "muscle_distribution": {"Rectus Abdominis": 60, "Transverse Abdominis": 40},
                "youtube_links": [
                    {"title": "Ab Wheel Rollout Proper Form & Hollow Body", "url": "https://www.youtube.com/watch?v=rqiTPdK1c_I"}
                ],
            },
            {
                "name": "Cable Woodchoppers",
                "muscle_group": "core",
                "category": "cable",
                "target_vector": "Rotational Oblique Power",
                "muscle_distribution": {"Internal & External Obliques": 75, "Rectus Abdominis": 25},
                "youtube_links": [
                    {"title": "Cable Woodchoppers for Obliques", "url": "https://www.youtube.com/watch?v=pAplQXk3dkU"}
                ],
            },
            {
                "name": "Cable Crunch",
                "muscle_group": "core",
                "category": "cable",
                "target_vector": "Spinal Flexion Weighted Core",
                "muscle_distribution": {"Upper Rectus Abdominis": 80, "Obliques": 20},
                "youtube_links": [
                    {"title": "Kneeling Cable Crunch Spinal Flexion", "url": "https://www.youtube.com/watch?v=2fO415v6zQo"}
                ],
            },
            # Additional Conditioning
            {
                "name": "Battle Ropes Slam",
                "muscle_group": "full_body",
                "category": "cardio",
                "target_vector": "Upper Body Anaerobic Power",
                "muscle_distribution": {"Cardiovascular": 50, "Shoulders & Arms": 30, "Core": 20},
                "youtube_links": [
                    {"title": "Battle Ropes Conditioning Techniques", "url": "https://www.youtube.com/watch?v=q6g4tQ20cHQ"}
                ],
            },
            {
                "name": "Sled / Prowler Push",
                "muscle_group": "full_body",
                "category": "machine",
                "target_vector": "Lower Body Concentric Drive",
                "muscle_distribution": {"Quadriceps": 45, "Gluteus & Calves": 35, "Cardiovascular": 20},
                "youtube_links": [
                    {"title": "Sled Prowler Push Full Body Conditioning", "url": "https://www.youtube.com/watch?v=jW8m3T2o71k"}
                ],
            },
        ]

        exercises = {}
        for ed in exercises_data:
            slug = slugify(ed["name"])
            obj, _ = Exercise.objects.update_or_create(
                slug=slug,
                created_by=None,
                defaults={
                    "name": ed["name"],
                    "muscle_group": ed["muscle_group"],
                    "category": ed["category"],
                    "target_vector": ed["target_vector"],
                    "muscle_distribution": ed["muscle_distribution"],
                    "youtube_links": ed.get("youtube_links", []),
                    "is_custom": False,
                },
            )
            exercises[ed["name"]] = obj

        self.stdout.write("Seeding predefined PPL & Hypertrophy routines...")
        routines_data = [
            # The 4 Primary Floor Sessions requested by user
            {
                "title": "Lower Body Session",
                "split_category": "lower",
                "focus_tag": "hypertrophy",
                "estimated_duration_minutes": 55,
                "description": "Guided lower body protocol targeting Quads, Hamstrings & Glutes, and Calves with grouped movement pairings.",
                "items": [
                    {"exercise": "Barbell Back Squat", "sets": 4, "reps": "8-10", "rest": 120},
                    {"exercise": "Leg Press", "sets": 3, "reps": "10-12", "rest": 90},
                    {"exercise": "Romanian Deadlift", "sets": 3, "reps": "8-10", "rest": 90},
                    {"exercise": "Lying Leg Curl", "sets": 3, "reps": "10-12", "rest": 75},
                    {"exercise": "Standing Calf Raise", "sets": 3, "reps": "12-15", "rest": 60},
                    {"exercise": "Seated Calf Raise", "sets": 3, "reps": "12-15", "rest": 60},
                ],
            },
            {
                "title": "Upper Body Session",
                "split_category": "upper",
                "focus_tag": "hypertrophy",
                "estimated_duration_minutes": 60,
                "description": "Comprehensive upper body protocol with paired targeting for Chest, Back, Shoulders, and Arms.",
                "items": [
                    {"exercise": "Barbell Bench Press", "sets": 4, "reps": "8-10", "rest": 90},
                    {"exercise": "Incline Dumbbell Press", "sets": 3, "reps": "10-12", "rest": 75},
                    {"exercise": "Barbell Bent-Over Row", "sets": 4, "reps": "8-10", "rest": 90},
                    {"exercise": "Pull-Ups", "sets": 3, "reps": "8-10", "rest": 90},
                    {"exercise": "Overhead Press", "sets": 3, "reps": "8-10", "rest": 90},
                    {"exercise": "Dumbbell Lateral Raise", "sets": 3, "reps": "12-15", "rest": 60},
                    {"exercise": "Barbell Bicep Curl", "sets": 3, "reps": "10-12", "rest": 60},
                    {"exercise": "Tricep Rope Pushdown", "sets": 3, "reps": "10-12", "rest": 60},
                ],
            },
            {
                "title": "Strength Session",
                "split_category": "full_body",
                "focus_tag": "strength",
                "estimated_duration_minutes": 60,
                "description": "Maximal compound force generation protocol across key neurological strength pillars.",
                "items": [
                    {"exercise": "Barbell Back Squat", "sets": 4, "reps": "4-6", "rest": 150},
                    {"exercise": "Conventional Deadlift", "sets": 3, "reps": "3-5", "rest": 180},
                    {"exercise": "Barbell Bench Press", "sets": 4, "reps": "5-6", "rest": 120},
                    {"exercise": "Barbell Bent-Over Row", "sets": 3, "reps": "6-8", "rest": 120},
                    {"exercise": "Overhead Press", "sets": 3, "reps": "5-6", "rest": 120},
                ],
            },
            {
                "title": "Endurance Session",
                "split_category": "full_body",
                "focus_tag": "recovery",
                "estimated_duration_minutes": 45,
                "description": "High-density functional stamina, aerobic pacing, and core stamina.",
                "items": [
                    {"exercise": "Rowing Machine Intervals", "sets": 4, "reps": "500m", "rest": 60},
                    {"exercise": "Assault Bike Sprints", "sets": 4, "reps": "45s", "rest": 60},
                    {"exercise": "Kettlebell Swings", "sets": 4, "reps": "20", "rest": 60},
                    {"exercise": "Push-Ups", "sets": 3, "reps": "15-20", "rest": 45},
                    {"exercise": "Plank Hold", "sets": 3, "reps": "60s", "rest": 45},
                    {"exercise": "Hanging Leg Raise", "sets": 3, "reps": "12-15", "rest": 45},
                    {"exercise": "Jump Rope Conditioning", "sets": 3, "reps": "2 min", "rest": 45},
                ],
            },
            # PPL & Classic protocols
            {
                "title": "PPL - Push Hyper-Drive",
                "split_category": "push",
                "focus_tag": "hypertrophy",
                "estimated_duration_minutes": 60,
                "description": "High-intensity chest, anterior delts, and triceps hypertrophy session.",
                "items": [
                    {"exercise": "Barbell Bench Press", "sets": 4, "reps": "8-10", "rest": 90},
                    {"exercise": "Incline Dumbbell Press", "sets": 3, "reps": "10-12", "rest": 75},
                    {"exercise": "Overhead Press", "sets": 3, "reps": "8-10", "rest": 90},
                    {"exercise": "Weighted Dips", "sets": 3, "reps": "10-12", "rest": 60},
                ],
            },
            {
                "title": "PPL - Pull Volume",
                "split_category": "pull",
                "focus_tag": "hypertrophy",
                "estimated_duration_minutes": 60,
                "description": "Upper and mid back thickness, lats, and bicep overload.",
                "items": [
                    {"exercise": "Barbell Bent-Over Row", "sets": 4, "reps": "8-10", "rest": 90},
                    {"exercise": "Pull-Ups", "sets": 3, "reps": "8-10", "rest": 90},
                    {"exercise": "Barbell Bicep Curl", "sets": 3, "reps": "10-12", "rest": 60},
                ],
            },
            {
                "title": "PPL - Legs & Posterior Chain",
                "split_category": "legs",
                "focus_tag": "strength",
                "estimated_duration_minutes": 65,
                "description": "Squat depth progression and posterior chain hamstring/glute drive.",
                "items": [
                    {"exercise": "Barbell Back Squat", "sets": 4, "reps": "6-8", "rest": 120},
                    {"exercise": "Romanian Deadlift", "sets": 3, "reps": "8-10", "rest": 90},
                    {"exercise": "Conventional Deadlift", "sets": 3, "reps": "5", "rest": 150},
                ],
            },
            {
                "title": "Alex's Chest Blast",
                "split_category": "push",
                "focus_tag": "hypertrophy",
                "estimated_duration_minutes": 45,
                "description": "High density chest pump protocol.",
                "items": [
                    {"exercise": "Barbell Bench Press", "sets": 5, "reps": "8-10", "rest": 90},
                    {"exercise": "Incline Dumbbell Press", "sets": 4, "reps": "10-12", "rest": 75},
                    {"exercise": "Weighted Dips", "sets": 3, "reps": "12-15", "rest": 60},
                ],
            },
        ]

        for rd in routines_data:
            routine, _ = Routine.objects.update_or_create(
                title=rd["title"],
                created_by=None,
                defaults={
                    "is_predefined": True,
                    "split_category": rd["split_category"],
                    "focus_tag": rd["focus_tag"],
                    "estimated_duration_minutes": rd["estimated_duration_minutes"],
                    "description": rd["description"],
                },
            )
            RoutineExercise.objects.filter(routine=routine).delete()
            for idx, item in enumerate(rd["items"], start=1):
                RoutineExercise.objects.create(
                    routine=routine,
                    exercise=exercises[item["exercise"]],
                    order=idx,
                    target_sets=item["sets"],
                    target_reps_range=item["reps"],
                    rest_protocol_seconds=item["rest"],
                )

        self.stdout.write("Seeding predefined recipes and cooking variations...")
        recipes_data = [
            {
                "title": "Crispy Lemon Herb Chicken Breast & Jasmine Rice",
                "base_prep_time_minutes": 15,
                "base_cook_time_minutes": 20,
                "base_calories": Decimal("520.00"),
                "base_protein_g": Decimal("48.00"),
                "base_carbs_g": Decimal("58.00"),
                "base_fat_g": Decimal("8.00"),
                "tags": ["Hypertrophy", "High Protein", "Clean Bulking"],
                "ingredients": [
                    {"name": "Chicken Breast", "amount": "220g", "protein": 46},
                    {"name": "Jasmine Rice (cooked)", "amount": "200g", "carbs": 56},
                    {"name": "Lemon Juice & Herbs", "amount": "30ml", "calories": 15},
                ],
                "instructions": [
                    "Butterfly the chicken breast and marinate with lemon juice, oregano, salt, and black pepper.",
                    "Cook according to your chosen cooking variation.",
                    "Serve with warm jasmine rice and steamed asparagus.",
                ],
                "variations": [
                    {
                        "variation_name": "Air Fryer Mode",
                        "temperature_details": "380°F (193°C)",
                        "cook_time_minutes": 14,
                        "calorie_offset": 35,
                        "macro_adjustment": {"fat_g": 4, "carbs_g": 0, "protein_g": 0},
                        "method_notes": "Preheat air fryer to 380°F. Spray lightly with avocado oil. Air fry for 14 minutes, flipping at halfway mark.",
                    },
                    {
                        "variation_name": "Gas Stove / Cast Iron Skillet",
                        "temperature_details": "400°F (204°C) medium-high heat",
                        "cook_time_minutes": 12,
                        "calorie_offset": 80,
                        "macro_adjustment": {"fat_g": 9, "carbs_g": 0, "protein_g": 0},
                        "method_notes": "Heat 1 tbsp extra virgin olive oil in cast iron skillet. Sear chicken 5-6 mins per side until golden brown crust forms.",
                    },
                ],
            },
            {
                "title": "Seared Salmon Bowl with Quinoa & Avocado",
                "base_prep_time_minutes": 10,
                "base_cook_time_minutes": 15,
                "base_calories": Decimal("610.00"),
                "base_protein_g": Decimal("42.00"),
                "base_carbs_g": Decimal("44.00"),
                "base_fat_g": Decimal("28.00"),
                "tags": ["Healthy Fats", "Omega-3", "Recovery"],
                "ingredients": [
                    {"name": "Atlantic Salmon Fillet", "amount": "200g", "protein": 40},
                    {"name": "Cooked Quinoa", "amount": "150g", "carbs": 32},
                    {"name": "Avocado", "amount": "50g", "fat": 8},
                ],
                "instructions": [
                    "Season salmon fillet with sea salt and garlic powder.",
                    "Cook skin-side down first for optimal crispness.",
                    "Plate over quinoa and top with sliced avocado.",
                ],
                "variations": [
                    {
                        "variation_name": "Air Fryer Mode",
                        "temperature_details": "400°F (204°C)",
                        "cook_time_minutes": 10,
                        "calorie_offset": 0,
                        "macro_adjustment": {},
                        "method_notes": "Place skin-side down in basket. No extra oil needed due to natural salmon omega-3 oils.",
                    },
                    {
                        "variation_name": "Gas Stove / Cast Iron Skillet",
                        "temperature_details": "Medium-high heat",
                        "cook_time_minutes": 8,
                        "calorie_offset": 45,
                        "macro_adjustment": {"fat_g": 5, "carbs_g": 0, "protein_g": 0},
                        "method_notes": "Sear skin side down for 5 mins until crisp, flip for remaining 3 mins.",
                    },
                ],
            },
            {
                "title": "High-Protein Greek Yogurt Parfait",
                "base_prep_time_minutes": 5,
                "base_cook_time_minutes": 0,
                "base_calories": Decimal("380.00"),
                "base_protein_g": Decimal("35.00"),
                "base_carbs_g": Decimal("42.00"),
                "base_fat_g": Decimal("6.00"),
                "tags": ["Quick Snack", "High Protein", "Breakfast"],
                "ingredients": [
                    {"name": "Non-fat Greek Yogurt", "amount": "250g", "protein": 25},
                    {"name": "Whey Protein Isolate (Vanilla)", "amount": "15g", "protein": 10},
                    {"name": "Blueberries & Honey", "amount": "80g", "carbs": 30},
                ],
                "instructions": [
                    "Whisk whey protein into Greek yogurt until smooth.",
                    "Layer in a bowl with fresh blueberries and a drizzle of honey.",
                ],
                "variations": [],
            },
        ]

        for rdata in recipes_data:
            slug = slugify(rdata["title"])
            recipe, _ = Recipe.objects.update_or_create(
                title=rdata["title"],
                created_by=None,
                defaults={
                    "slug": slug,
                    "is_predefined": True,
                    "base_prep_time_minutes": rdata["base_prep_time_minutes"],
                    "base_cook_time_minutes": rdata["base_cook_time_minutes"],
                    "base_calories": rdata["base_calories"],
                    "base_protein_g": rdata["base_protein_g"],
                    "base_carbs_g": rdata["base_carbs_g"],
                    "base_fat_g": rdata["base_fat_g"],
                    "tags": rdata["tags"],
                    "ingredients_json": rdata["ingredients"],
                    "instructions": rdata["instructions"],
                },
            )
            CookingVariation.objects.filter(recipe=recipe).delete()
            for vdata in rdata["variations"]:
                CookingVariation.objects.create(
                    recipe=recipe,
                    variation_name=vdata["variation_name"],
                    temperature_details=vdata["temperature_details"],
                    cook_time_minutes=vdata["cook_time_minutes"],
                    calorie_offset=vdata["calorie_offset"],
                    macro_adjustment=vdata["macro_adjustment"],
                    method_notes=vdata["method_notes"],
                )

        self.stdout.write("Seeding fitness knowledge feed articles...")
        from fitness.models import Article

        articles_data = [
            {
                "title": "The Science of Hypertrophy: Rep Ranges & Mechanical Tension",
                "url": "https://rpstrength.com/blogs/articles/hypertrophy-training-guide",
                "excerpt": "Evidence-based breakdown on why 5-30 reps stimulate equal muscle growth when taken close to failure, and how to calibrate volume per muscle group.",
                "source": "Renaissance Periodization",
                "category": "training",
                "tags": ["Hypertrophy", "Volume", "Science", "RPE"],
                "reading_time_minutes": 7,
                "cover_image_url": "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?w=800&auto=format&fit=crop&q=60",
                "is_pinned": True,
            },
            {
                "title": "Optimal Daily Protein Distribution & Leucine Threshold",
                "url": "https://www.strongerbyscience.com/protein-recommendations/",
                "excerpt": "How much protein do strength athletes truly need? Examining the 1.6-2.2g/kg rule, meal timing, and triggering muscle protein synthesis.",
                "source": "Stronger by Science",
                "category": "nutrition",
                "tags": ["Protein", "Macros", "Nutrition", "MPS"],
                "reading_time_minutes": 6,
                "cover_image_url": "https://images.unsplash.com/photo-1490645935967-10de6ba17061?w=800&auto=format&fit=crop&q=60",
                "is_pinned": True,
            },
            {
                "title": "Sleep Architecture & Neuromuscular Recovery in Heavy Lifters",
                "url": "https://www.barbellmedicine.com/blog/sleep-and-athletic-performance/",
                "excerpt": "Understanding slow-wave delta sleep, growth hormone secretion, and why sub-7 hour sleep blocks impair 1RM force output.",
                "source": "Barbell Medicine",
                "category": "recovery",
                "tags": ["Sleep", "Recovery", "CNS", "Hormones"],
                "reading_time_minutes": 5,
                "cover_image_url": "https://images.unsplash.com/photo-1541781774459-bb2af2f05b55?w=800&auto=format&fit=crop&q=60",
                "is_pinned": False,
            },
            {
                "title": "Shoulder Health & Rotator Cuff Prehab for Heavy Pressers",
                "url": "https://squatuniversity.com/2018/06/21/how-to-fix-shoulder-pain-bench-pressing/",
                "excerpt": "Prevent impingement and AC joint wear with external rotation drills, face pulls, and proper scapular retraction on the bench.",
                "source": "Squat University",
                "category": "injury_prevention",
                "tags": ["Shoulder Health", "Prehab", "Bench Press", "Form"],
                "reading_time_minutes": 8,
                "cover_image_url": "https://images.unsplash.com/photo-1581009146145-b5ef050c2e1e?w=800&auto=format&fit=crop&q=60",
                "is_pinned": False,
            },
            {
                "title": "Creatine Monohydrate: Complete Evidence-Based Usage Guide",
                "url": "https://examine.com/supplements/creatine/",
                "excerpt": "The most researched sports supplement in history: dosing strategies, saturation phases, hydration demands, and brain cognition benefits.",
                "source": "Examine.com",
                "category": "science",
                "tags": ["Creatine", "Supplements", "Hydration", "Power"],
                "reading_time_minutes": 4,
                "cover_image_url": "https://images.unsplash.com/photo-1579722821273-0f6c7d44362f?w=800&auto=format&fit=crop&q=60",
                "is_pinned": False,
            },
            {
                "title": "Progressive Overload Without Adding Weight: Density & Tempo",
                "url": "https://gyma.fit/guides/progressive-overload-principles",
                "excerpt": "Plateaued on the barbell? Learn how altering eccentric cadence, shortening rest intervals, and improving form yield massive gains.",
                "source": "Gym Coaching Staff",
                "category": "training",
                "tags": ["Progressive Overload", "Tempo", "Coaching", "Hypertrophy"],
                "reading_time_minutes": 5,
                "cover_image_url": "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?w=800&auto=format&fit=crop&q=60",
                "is_pinned": False,
            },
        ]

        for ad in articles_data:
            Article.objects.update_or_create(
                url=ad["url"],
                defaults={
                    "title": ad["title"],
                    "excerpt": ad["excerpt"],
                    "source": ad["source"],
                    "category": ad["category"],
                    "tags": ad["tags"],
                    "reading_time_minutes": ad["reading_time_minutes"],
                    "cover_image_url": ad["cover_image_url"],
                    "is_pinned": ad["is_pinned"],
                },
            )

        self.stdout.write(self.style.SUCCESS("Successfully seeded fitness data!"))
