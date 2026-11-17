"""
Diet and lifestyle *education*, personalised from the user's own lab results and health profile.

Design rules (safety first):
  - Content is curated, conservative, public-health guidance from named sources (WHO, MedlinePlus,
    NIH Office of Dietary Supplements). Nothing here is generated; every item cites its source.
  - A rule only fires from a result the laboratory itself placed outside its printed reference range
    (or flagged H/L). Values are never re-interpreted against other ranges.
  - Where diet must be individual (kidney, electrolytes, liver, thyroid, low sugar, critical values),
    no food list is given: the item says so and asks the user to speak with their doctor.
  - Never: doses, supplements to start, medicines to change, or claims that food cures a disease.
  - Allergies and dietary preference from the profile remove foods; missing information is reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import F as DbF

from .logic import range_info
from .models import LabParameter

SOURCES = {
    "who_diet": ("WHO: Healthy diet (fact sheet)", "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"),
    "who_activity": ("WHO: Physical activity (fact sheet)", "https://www.who.int/news-room/fact-sheets/detail/physical-activity"),
    "mlp_nutrition": ("MedlinePlus: Nutrition", "https://medlineplus.gov/nutrition.html"),
    "mlp_chol_diet": ("MedlinePlus: How to Lower Cholesterol with Diet", "https://medlineplus.gov/howtolowercholesterolwithdiet.html"),
    "mlp_fats": ("MedlinePlus: Dietary Fats", "https://medlineplus.gov/dietaryfats.html"),
    "mlp_cholesterol": ("MedlinePlus: Cholesterol", "https://medlineplus.gov/cholesterol.html"),
    "mlp_tg": ("MedlinePlus: Triglycerides Test", "https://medlineplus.gov/lab-tests/triglycerides-test/"),
    "mlp_carbs": ("MedlinePlus: Carbohydrates", "https://medlineplus.gov/carbohydrates.html"),
    "mlp_diabetic_diet": ("MedlinePlus: Diabetic Diet", "https://medlineplus.gov/diabeticdiet.html"),
    "mlp_diabetes": ("MedlinePlus: Diabetes", "https://medlineplus.gov/diabetes.html"),
    "mlp_glucose": ("MedlinePlus: Blood Glucose Test", "https://medlineplus.gov/lab-tests/blood-glucose-test/"),
    "mlp_anemia": ("MedlinePlus: Anemia", "https://medlineplus.gov/anemia.html"),
    "mlp_iron": ("MedlinePlus: Iron", "https://medlineplus.gov/iron.html"),
    "ods_iron": ("NIH Office of Dietary Supplements: Iron fact sheet", "https://ods.od.nih.gov/factsheets/Iron-Consumer/"),
    "mlp_vitd": ("MedlinePlus: Vitamin D", "https://medlineplus.gov/vitamind.html"),
    "ods_vitd": ("NIH Office of Dietary Supplements: Vitamin D fact sheet", "https://ods.od.nih.gov/factsheets/VitaminD-Consumer/"),
    "ods_b12": ("NIH Office of Dietary Supplements: Vitamin B12 fact sheet", "https://ods.od.nih.gov/factsheets/VitaminB12-Consumer/"),
    "mlp_uric": ("MedlinePlus: Uric Acid Test", "https://medlineplus.gov/lab-tests/uric-acid-test/"),
    "mlp_kidney": ("MedlinePlus: Kidney Diseases", "https://medlineplus.gov/kidneydiseases.html"),
    "mlp_bmp": ("MedlinePlus: Basic Metabolic Panel", "https://medlineplus.gov/lab-tests/basic-metabolic-panel-bmp/"),
    "mlp_liver": ("MedlinePlus: Liver Function Tests", "https://medlineplus.gov/lab-tests/liver-function-tests/"),
    "mlp_thyroid": ("MedlinePlus: Hypothyroidism", "https://medlineplus.gov/hypothyroidism.html"),
    "mlp_sodium": ("MedlinePlus: Sodium", "https://medlineplus.gov/sodium.html"),
    "mlp_fiber": ("MedlinePlus: Dietary Fiber", "https://medlineplus.gov/dietaryfiber.html"),
    "mlp_protein": ("MedlinePlus: Dietary Proteins", "https://medlineplus.gov/dietaryproteins.html"),
    "mlp_exercise": ("MedlinePlus: Exercise and Physical Fitness", "https://medlineplus.gov/exerciseandphysicalfitness.html"),
    "mlp_weight": ("MedlinePlus: Weight Control", "https://medlineplus.gov/weightcontrol.html"),
    "mlp_smoking": ("MedlinePlus: Smoking", "https://medlineplus.gov/smoking.html"),
    "mlp_sleep": ("MedlinePlus: Sleep Disorders", "https://medlineplus.gov/sleepdisorders.html"),
    "mlp_stress": ("MedlinePlus: Stress", "https://medlineplus.gov/stress.html"),
    "mlp_healthy": ("MedlinePlus: Healthy Living", "https://medlineplus.gov/healthyliving.html"),
    "mlp_dehydration": ("MedlinePlus: Dehydration", "https://medlineplus.gov/dehydration.html"),
}

DISCLAIMER = (
    "General health education from public sources, not medical advice or a treatment plan. It does not "
    "diagnose, treat or cure any condition. Keep taking your medicines exactly as prescribed, and talk to "
    "your doctor or a registered dietitian before making major changes, especially if you are pregnant, "
    "have a long-term condition or take regular medicines."
)

LABELS = {
    "hemoglobin": "Hemoglobin", "hba1c": "HbA1c", "glucose_fasting": "Fasting glucose",
    "glucose_postprandial": "Post-meal glucose", "glucose_random": "Random glucose", "creatinine": "Creatinine",
    "urea": "Urea", "bun": "Blood urea nitrogen", "uric_acid": "Uric acid", "cholesterol_total": "Total cholesterol",
    "hdl": "HDL cholesterol", "ldl": "LDL cholesterol", "triglycerides": "Triglycerides", "alt": "ALT (SGPT)",
    "ast": "AST (SGOT)", "bilirubin_total": "Total bilirubin", "tsh": "TSH", "t3": "T3", "t4": "T4",
    "vitamin_d": "Vitamin D", "vitamin_b12": "Vitamin B12", "ferritin": "Ferritin", "sodium": "Sodium",
    "potassium": "Potassium",
}

# --------------------------------------------------------------------------- foods


@dataclass(frozen=True)
class Food:
    name: str
    note: str  # qualitative nutrition information from the cited source; no invented numbers
    tags: frozenset = frozenset()  # meat, fish, egg, dairy, nuts, peanut, gluten, soy, sesame


def F(name, note, *tags):
    return Food(name, note, frozenset(tags))


# Allergy words a user may type -> food tags they exclude.
ALLERGY_TAGS = {
    r"\bpeanut|groundnut": {"peanut"},
    r"\bnut|almond|walnut|cashew|pistachio": {"nuts"},
    r"\bmilk|dairy|lactose|curd|paneer|casein|whey": {"dairy"},
    r"\begg": {"egg"},
    r"\bfish|seafood|shellfish|prawn|shrimp|crab": {"fish"},
    r"\bgluten|wheat|celiac|coeliac": {"gluten"},
    r"\bsoy|soya": {"soy"},
    r"\bsesame|\btil\b": {"sesame"},
}
DIET_EXCLUDES = {
    "vegan": {"meat", "fish", "egg", "dairy"},
    "vegetarian": {"meat", "fish", "egg"},
    "eggetarian": {"meat", "fish"},
    "pescatarian": {"meat"},
}


@dataclass
class Context:
    findings: dict  # normalized parameter -> finding dict
    excluded_tags: set
    allergies_text: str
    dietary_preference: str
    age: int | None
    bmi: Decimal | None
    chronic_conditions: str
    missing: list = field(default_factory=list)

    def status(self, *names):
        """'high' | 'low' | None for the first of `names` that the lab placed outside its range."""
        for n in names:
            f = self.findings.get(n)
            if f and f["direction"]:
                return f["direction"]
        return None

    def triggered_by(self, *names, direction=None):
        return [self.findings[n] for n in names
                if n in self.findings and self.findings[n]["direction"] and
                (direction is None or self.findings[n]["direction"] == direction)]

    def allowed(self, foods):
        kept, removed = [], []
        for food in foods:
            (removed if food.tags & self.excluded_tags else kept).append(food)
        return kept, removed


def _src(*keys):
    return [{"title": SOURCES[k][0], "url": SOURCES[k][1]} for k in keys]


def _why(findings):
    parts = [f"{f['label']} {f['value_text']} {f['unit']}".strip() +
             (f" (lab range {f['reference_range_text']})" if f["reference_range_text"] else "") +
             f", marked {f['direction']} on your report of {f['report_date']}" for f in findings]
    return "Suggested because: " + "; ".join(parts) + "."


def _food_list(ctx, foods):
    kept, removed = ctx.allowed(foods)
    return [{"name": f.name, "note": f.note} for f in kept], [f.name for f in removed]


# --------------------------------------------------------------------------- diet rules

def _diet_items(ctx: Context) -> list[dict]:
    items = []

    def add(id_, title, findings, summary, include=(), limit=(), tips=(), sources=(), needs_doctor=False,
            doctor_note=""):
        inc, removed = _food_list(ctx, include)
        items.append({"id": id_, "title": title, "why": _why(findings) if findings else "", "summary": summary,
                      "include": inc, "limit": list(limit), "tips": list(tips), "removed_for_you": removed,
                      "needs_doctor": needs_doctor, "doctor_note": doctor_note, "sources": _src(*sources),
                      "based_on": [f["parameter"] for f in findings]})

    lipids = ctx.triggered_by("ldl", "cholesterol_total", "triglycerides", direction="high") + ctx.triggered_by("hdl", direction="low")
    if ctx.triggered_by("ldl", "cholesterol_total", direction="high") or ctx.triggered_by("hdl", direction="low"):
        add("heart_healthy_fats", "Heart-healthy fats and more fibre", lipids,
            "Eating less saturated and trans fat and more soluble fibre is a recommended first step for cholesterol.",
            include=[F("Oats, barley and whole grains", "Contain soluble fibre, which can help lower LDL cholesterol."),
                     F("Dals, rajma, chana and other legumes", "Fibre and plant protein."),
                     F("Vegetables and fruits", "Fibre; naturally low in saturated fat."),
                     F("Small handful of unsalted nuts (almonds, walnuts)", "Mostly unsaturated fats.", "nuts"),
                     F("Fish such as mackerel or sardines", "Omega-3 (unsaturated) fats.", "fish"),
                     F("Cooking oils like mustard, groundnut or rice-bran oil, in small amounts", "Mainly unsaturated fats.", "peanut")],
            limit=["Fried snacks and bakery items made with vanaspati or shortening (trans fats)",
                   "Large amounts of ghee, butter, cream and coconut oil (saturated fats)",
                   "Processed and red meats", "Full-fat sweets and desserts"],
            sources=("mlp_chol_diet", "mlp_fats", "mlp_cholesterol"),
            doctor_note="If you take a cholesterol medicine, keep taking it as prescribed; diet works alongside it.")

    if ctx.triggered_by("triglycerides", direction="high"):
        add("lower_triglycerides", "Less sugar, refined carbs and alcohol",
            ctx.triggered_by("triglycerides", direction="high"),
            "Triglycerides rise with sugar, refined carbohydrates and alcohol.",
            include=[F("Whole grains and millets (ragi, jowar, bajra) instead of maida", "More fibre than refined flour."),
                     F("Vegetables and legumes", "Fibre with little sugar."),
                     F("Fish such as mackerel or sardines", "Omega-3 fats.", "fish")],
            limit=["Sugar, sweets and sugary drinks, including packaged fruit juice", "White bread, maida and other refined flours",
                   "Alcohol"],
            sources=("mlp_tg", "mlp_carbs", "mlp_fats"))

    sugar_high = ctx.triggered_by("hba1c", "glucose_fasting", "glucose_postprandial", "glucose_random", direction="high")
    if sugar_high:
        add("blood_sugar", "Steadier blood sugar", sugar_high,
            "Regular meals, high-fibre carbohydrates in sensible portions and fewer sugary foods help keep blood sugar steadier.",
            include=[F("Whole grains and millets (brown rice, ragi, jowar, whole-wheat roti)", "Fibre slows the rise in blood sugar.", "gluten"),
                     F("Non-starchy vegetables (leafy greens, beans, gourds, cauliflower)", "Fibre with few carbohydrates."),
                     F("Dals, chana, sprouts and paneer or eggs for protein at each meal", "Protein helps with fullness.", "dairy", "egg"),
                     F("Whole fruits instead of juice", "Whole fruit keeps its fibre.")],
            limit=["Sugar, sweets, honey and jaggery", "Sugary drinks and fruit juices",
                   "Large portions of white rice, maida and potatoes", "Fried snacks"],
            tips=["Eat at regular times and do not skip meals.", "Use a plate method: half vegetables, a quarter whole grains, a quarter protein."],
            sources=("mlp_diabetic_diet", "mlp_diabetes", "mlp_carbs"),
            needs_doctor=True,
            doctor_note="If you take diabetes medicines or insulin, ask your doctor before changing how much or when you eat: "
                        "changes can cause low blood sugar.")

    if ctx.triggered_by("glucose_fasting", "glucose_random", "glucose_postprandial", direction="low"):
        add("low_sugar", "Low blood sugar needs a doctor's review",
            ctx.triggered_by("glucose_fasting", "glucose_random", "glucose_postprandial", direction="low"),
            "A low blood sugar result needs medical evaluation; it isn't something to manage with a diet plan on your own.",
            sources=("mlp_glucose",), needs_doctor=True,
            doctor_note="Talk to your doctor about this result. If you feel shaky, sweaty or confused, seek medical help.")

    iron = ctx.triggered_by("hemoglobin", "ferritin", direction="low")
    if iron:
        add("iron_rich", "Iron-rich foods", iron,
            "Low hemoglobin or ferritin can have many causes; iron-rich foods are one part of the picture.",
            include=[F("Green leafy vegetables (spinach, amaranth, methi)", "Plant (non-heme) iron."),
                     F("Dals, rajma, chana, soybeans and tofu", "Plant iron and protein.", "soy"),
                     F("Eggs, fish, chicken or lean meat", "Heme iron, which the body absorbs more easily.", "egg", "fish", "meat"),
                     F("Vitamin C foods with meals: amla, guava, oranges, lemon, tomatoes", "Vitamin C helps the body absorb plant iron.")],
            limit=["Tea or coffee with meals (they reduce iron absorption; have them between meals instead)"],
            sources=("mlp_anemia", "mlp_iron", "ods_iron"), needs_doctor=True,
            doctor_note="Ask your doctor what is causing the low result. Don't start iron tablets on your own: the cause "
                        "and the right treatment need a doctor.")

    if ctx.triggered_by("vitamin_d", direction="low"):
        add("vitamin_d", "Vitamin D sources", ctx.triggered_by("vitamin_d", direction="low"),
            "Few foods are naturally rich in vitamin D; the skin also makes it in sunlight.",
            include=[F("Fatty fish such as salmon, sardines or mackerel", "Among the best natural food sources.", "fish"),
                     F("Egg yolks", "Contain small amounts.", "egg"),
                     F("Milk or other foods labelled as fortified with vitamin D", "Fortified foods provide most dietary vitamin D.", "dairy"),
                     F("Mushrooms exposed to sunlight or UV light", "Contain some vitamin D.")],
            sources=("mlp_vitd", "ods_vitd"), needs_doctor=True,
            doctor_note="Whether you need a vitamin D supplement, and how much, should be decided by your doctor; too much can be harmful.")

    if ctx.triggered_by("vitamin_b12", direction="low"):
        add("vitamin_b12", "Vitamin B12 sources", ctx.triggered_by("vitamin_b12", direction="low"),
            "Vitamin B12 is found naturally in animal foods; vegetarians and vegans often rely on dairy or fortified foods.",
            include=[F("Milk, curd and paneer", "Natural sources of B12.", "dairy"),
                     F("Eggs", "Natural source of B12.", "egg"),
                     F("Fish, chicken and meat", "Rich natural sources.", "fish", "meat"),
                     F("Foods labelled as fortified with vitamin B12 (some cereals, plant milks)", "Main source for vegans.")],
            sources=("ods_b12",), needs_doctor=True,
            doctor_note="Low B12 often needs treatment from a doctor; food alone may not be enough to correct it.")

    if ctx.triggered_by("uric_acid", direction="high"):
        add("uric_acid", "Lower-purine choices", ctx.triggered_by("uric_acid", direction="high"),
            "Some foods and drinks raise uric acid. Limiting them is commonly advised.",
            include=[F("Water through the day", "Helps the kidneys remove uric acid."),
                     F("Vegetables, whole grains and low-fat dairy", "Generally lower in purines.", "dairy")],
            limit=["Organ meats (liver, kidney) and large amounts of red meat", "Shellfish and some oily fish",
                   "Sugary drinks sweetened with fructose", "Alcohol, especially beer"],
            sources=("mlp_uric",), doctor_note="If you have gout or kidney stones, follow your doctor's plan.")

    kidney = ctx.triggered_by("creatinine", "urea", "bun", direction="high") + ctx.triggered_by("potassium", "sodium")
    if kidney:
        add("kidney_individual", "Kidney and electrolyte results: diet must be individual", kidney,
            "Protein, potassium, salt and fluid needs depend on the exact kidney or electrolyte problem, so AyuMitra "
            "does not suggest foods for these results.",
            sources=("mlp_kidney", "mlp_bmp"), needs_doctor=True,
            doctor_note="Ask your doctor, or a renal dietitian, before changing your diet, fluids or salt.")

    liver = ctx.triggered_by("alt", "ast", "bilirubin_total", direction="high")
    if liver:
        add("liver", "Liver test results", liver,
            "Raised liver tests have many causes that need a doctor's evaluation.",
            limit=["Alcohol", "Fried and very fatty foods", "Sugary drinks",
                   "Herbal or 'liver detox' products, unless your doctor approves them"],
            sources=("mlp_liver",), needs_doctor=True,
            doctor_note="Talk to your doctor about the cause. Don't take new supplements or herbal products without asking.")

    thyroid = ctx.triggered_by("tsh", "t3", "t4")
    if thyroid:
        add("thyroid", "Thyroid results", thyroid,
            "No diet corrects thyroid levels; thyroid results are managed by your doctor.",
            sources=("mlp_thyroid",), needs_doctor=True,
            doctor_note="If you take thyroid medicine, take it exactly as your doctor or pharmacist directed, including timing around meals.")

    # Baseline for everyone.
    add("balanced_plate", "A balanced everyday diet", [],
        "Recommended for everyone: a variety of foods, plenty of vegetables, fruits, legumes and whole grains, and less salt, sugar and unhealthy fat.",
        include=[F("Vegetables and fruits at every meal", "WHO advises at least 400 g (five portions) a day."),
                 F("Legumes, whole grains and millets", "Fibre, protein and minerals."),
                 F("Curd or buttermilk", "Protein and calcium.", "dairy")],
        limit=["Salt: WHO advises less than 5 g a day (about one teaspoon), including salt in pickles, papad and packaged foods",
               "Free sugars: less than 10% of daily energy", "Trans fats from vanaspati and many fried or packaged snacks"],
        sources=("who_diet", "mlp_nutrition", "mlp_sodium", "mlp_fiber"))
    return items


# --------------------------------------------------------------------------- meal plan

MEALS = {
    "breakfast": [F("Vegetable poha with a few roasted peanuts", "Add vegetables for fibre.", "peanut"),
                  F("Moong dal chilla with mint chutney", "Protein from moong dal."),
                  F("Idli with sambar", "Sambar adds dal and vegetables."),
                  F("Oats porridge made with milk, topped with fruit", "Soluble fibre from oats.", "dairy"),
                  F("Two boiled eggs with whole-wheat toast", "Protein and whole grain.", "egg", "gluten")],
    "lunch": [F("Millet or brown rice, dal, a vegetable sabzi and salad", "Plate: half vegetables."),
              F("Whole-wheat roti, rajma or chana, vegetables and curd", "Fibre and protein.", "gluten", "dairy"),
              F("Rice, fish curry, vegetables and salad", "Omega-3 fats from fish.", "fish")],
    "snacks": [F("A whole fruit such as guava, orange or apple", "Fibre and vitamin C."),
               F("Roasted chana", "Protein and fibre."),
               F("Sprouts salad with lemon", "Protein; vitamin C from lemon."),
               F("Buttermilk (unsweetened)", "Protein and calcium.", "dairy"),
               F("A small handful of unsalted nuts", "Unsaturated fats.", "nuts")],
    "dinner": [F("Vegetable khichdi (rice and moong dal) with salad", "Light, with protein from dal."),
               F("Whole-wheat roti with palak dal and a vegetable", "Iron and fibre from greens and dal.", "gluten"),
               F("Grilled chicken or paneer with sautéed vegetables", "Protein with vegetables.", "meat", "dairy")],
}


def _meal_plan(ctx: Context, blocking: bool) -> dict:
    if blocking:
        return {"available": False, "slots": {},
                "message": "A sample meal plan isn't shown because one of your results (kidney, electrolytes, liver or "
                           "low sugar) needs an individual diet from your doctor or dietitian."}
    slots = {}
    for slot, options in MEALS.items():
        kept, _ = ctx.allowed(options)
        slots[slot] = [{"name": f.name, "note": f.note} for f in kept[:2]]
    return {"available": True, "slots": slots,
            "message": "A sample day of ideas, not a prescription. Portions depend on your age, activity and health; "
                       "a registered dietitian can tailor them."}


# --------------------------------------------------------------------------- lifestyle

def _lifestyle_items(ctx: Context) -> list[dict]:
    items = []
    critical = any(f["critical"] for f in ctx.findings.values())
    kidney = bool(ctx.triggered_by("creatinine", "urea", "bun", direction="high") + ctx.triggered_by("potassium", "sodium"))
    sugar_high = ctx.triggered_by("hba1c", "glucose_fasting", "glucose_postprandial", "glucose_random", direction="high")
    has_conditions = bool(ctx.chronic_conditions.strip())

    def add(id_, title, summary, tips, sources, needs_doctor=False, doctor_note="", findings=()):
        items.append({"id": id_, "title": title, "summary": summary, "tips": list(tips),
                      "why": _why(list(findings)) if findings else "", "needs_doctor": needs_doctor,
                      "doctor_note": doctor_note, "sources": _src(*sources),
                      "based_on": [f["parameter"] for f in findings]})

    age = ctx.age
    if age is not None and age < 18:
        activity = ("Children and teenagers (5–17 years): WHO recommends an average of 60 minutes a day of moderate "
                    "to vigorous activity, mostly aerobic.")
    else:
        activity = ("Adults: WHO recommends 150–300 minutes a week of moderate activity (for example brisk walking), "
                    "or 75–150 minutes of vigorous activity, plus muscle-strengthening on 2 or more days a week.")
    tips = ["Start slowly and build up; some activity is better than none.", "Break up long periods of sitting.",
            "Choose something you enjoy: walking, cycling, yoga, swimming, dancing or sport."]
    if age is not None and age >= 65:
        tips.append("At 65 and over, WHO also advises balance and strength activities on 3 or more days a week to prevent falls.")
    if sugar_high:
        tips.append("Regular activity helps your body use insulin and can lower blood sugar.")
    doctor_reasons = []
    if critical:
        doctor_reasons.append("a result your lab marked as critical")
    if kidney:
        doctor_reasons.append("kidney or electrolyte results outside the range")
    if sugar_high:
        doctor_reasons.append("raised blood sugar (if you take diabetes medicines, ask how to avoid low sugar during exercise)")
    if has_conditions:
        doctor_reasons.append("the long-term conditions in your profile")
    if age is not None and age >= 65:
        doctor_reasons.append("your age, if you're starting something new")
    add("activity", "Physical activity", activity, tips, ("who_activity", "mlp_exercise"),
        needs_doctor=bool(doctor_reasons),
        doctor_note=("Check with your doctor before starting a new or more intense exercise programme because of "
                     + "; ".join(doctor_reasons) + ".") if doctor_reasons else
        "Stop and seek medical advice if you get chest pain, severe breathlessness, dizziness or fainting during exercise.",
        findings=sugar_high)

    sleep = ("Most adults need 7 or more hours of sleep a night; teenagers need more (8–10 hours)."
             if age is None or age >= 18 else "Teenagers need 8–10 hours of sleep a night; younger children need more.")
    add("sleep", "Sleep", sleep,
        ["Go to bed and wake up at the same times every day, including weekends.",
         "Avoid caffeine late in the day and heavy meals close to bedtime.",
         "Keep the bedroom dark, quiet and cool, and put screens away before bed.",
         "Regular daytime activity helps sleep."],
        ("mlp_sleep",),
        doctor_note="See a doctor if you snore loudly, stop breathing during sleep, or feel very sleepy in the day; these "
                    "can be signs of a sleep disorder.")

    fluid_limit = kidney or bool(re.search(r"heart failure|kidney|renal|dialysis|liver|cirrhosis", ctx.chronic_conditions, re.I))
    add("hydration", "Hydration",
        "Drink water regularly through the day and choose water over sugary drinks. You need more in hot weather, "
        "during exercise, and with fever, vomiting or diarrhoea.",
        ["Keep a water bottle with you.", "Pale yellow urine is a sign you are drinking enough.",
         "Sugary drinks and packaged juices add sugar without nutrition."],
        ("mlp_dehydration", "who_diet"),
        needs_doctor=fluid_limit,
        doctor_note="With kidney, heart or liver conditions, or kidney or electrolyte results outside the range, you may "
                    "have a fluid limit. Ask your doctor how much to drink." if fluid_limit else "",
        findings=ctx.triggered_by("creatinine", "urea", "bun", direction="high") + ctx.triggered_by("potassium", "sodium"))

    add("stress", "Stress management",
        "Long-term stress affects sleep, blood pressure, blood sugar and mood. Small daily habits help.",
        ["Try slow breathing, meditation or yoga for a few minutes each day.", "Stay physically active.",
         "Keep in touch with family and friends, and share how you feel.",
         "Limit news and screen time if it adds to stress.",
         "If you feel low or anxious for more than two weeks, or can't cope, talk to a doctor or counsellor. "
         "Tele-MANAS (free, 24×7, India): call 14416 or 1-800-891-4416."],
        ("mlp_stress",),
        doctor_note="If you have thoughts of harming yourself, call 112 or Tele-MANAS 14416 now.")

    habits = ["Don't use tobacco in any form; quitting at any age helps.",
              "Avoid alcohol, or keep it to a minimum: less is better for health.",
              "Get regular health check-ups and repeat tests when your doctor advises."]
    weight_summary = "Healthy daily habits lower the risk of heart disease, diabetes and other long-term conditions."
    if ctx.bmi is not None:
        weight_summary += (f" Your BMI from your profile is {ctx.bmi}. For Indian adults, national guidance treats 23 and "
                           "above as overweight, because health risks start at a lower BMI than in some other populations.")
    elif "height_cm" in ctx.missing or "weight_kg" in ctx.missing:
        habits.append("Add your height and weight in Settings to see your BMI.")
    add("habits", "Daily healthy habits", weight_summary, habits, ("mlp_smoking", "mlp_weight", "mlp_healthy"))
    return items


# --------------------------------------------------------------------------- entry point

def _latest_findings(user) -> tuple[dict, int, str | None]:
    """Most recent value per test across the user's reports (by report date)."""
    params = (LabParameter.objects.filter(report__document__owner=user)
              .select_related("report__document")
              .order_by(DbF("report__report_date").desc(nulls_last=True), "-report__created_at"))
    out, reports = {}, set()
    latest = None
    for p in params:
        key = p.normalized_name or p.name_as_printed.lower().strip()
        rep = p.report
        reports.add(rep.pk)
        rdate = rep.report_date or rep.document.document_date or rep.document.created_at.date()
        latest = max(latest, rdate) if latest else rdate
        if key in out:
            continue
        rs = range_info(p)["status"]
        direction = {"above": "high", "below": "low"}.get(rs)
        if not direction and p.lab_flag:
            direction = {"high": "high", "critical_high": "high", "low": "low", "critical_low": "low"}.get(p.lab_flag)
        out[key] = {"parameter": key, "label": p.name_as_printed or LABELS.get(key, key), "value_text": p.value_text,
                    "unit": p.unit, "reference_range_text": p.reference_range_text, "direction": direction,
                    "critical": p.lab_flag in ("critical_high", "critical_low"), "lab_flag": p.lab_flag,
                    "report_id": rep.pk, "report_date": rdate.isoformat(), "user_verified": p.user_verified}
    return out, len(reports), latest.isoformat() if latest else None


def _age(dob, today=None):
    if not dob:
        return None
    today = today or date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def build_recommendations(user) -> dict:
    from patients.models import PatientProfile

    profile, _ = PatientProfile.objects.get_or_create(user=user)
    findings, n_reports, latest = _latest_findings(user)

    allergy_tags = set()
    for pattern, tags in ALLERGY_TAGS.items():
        if re.search(pattern, profile.allergies or "", re.I):
            allergy_tags |= tags
    excluded = set(allergy_tags)
    pref = (profile.dietary_preference or "").lower()
    for word, tags in DIET_EXCLUDES.items():
        if word in pref:
            excluded |= tags
            break

    bmi = None
    if profile.height_cm and profile.weight_kg:
        h = Decimal(profile.height_cm) / 100
        bmi = (Decimal(profile.weight_kg) / (h * h)).quantize(Decimal("0.1"))
    missing = [f for f in ("date_of_birth", "height_cm", "weight_kg") if not getattr(profile, f)]
    if not profile.dietary_preference:
        missing.append("dietary_preference")

    ctx = Context(findings=findings, excluded_tags=excluded, allergies_text=profile.allergies or "",
                  dietary_preference=profile.dietary_preference or "", age=_age(profile.date_of_birth), bmi=bmi,
                  chronic_conditions=profile.chronic_conditions or "", missing=missing)

    alerts = []
    for f in findings.values():
        if f["critical"]:
            alerts.append(f"Your lab marked {f['label']} ({f['value_text']} {f['unit']}) as critical on {f['report_date']}. "
                          "Contact your doctor promptly; diet and lifestyle changes are not a substitute for care.")
    unverified = [f["label"] for f in findings.values() if f["direction"] and not f["user_verified"]]

    diet = _diet_items(ctx)
    blocking = any(i["id"] in ("kidney_individual", "liver", "low_sugar") for i in diet)
    return {
        "generated_from": {"reports_used": n_reports, "latest_report_date": latest,
                           "results_outside_range": sum(1 for f in findings.values() if f["direction"]),
                           "dietary_preference": profile.dietary_preference or None,
                           "allergies_considered": bool(profile.allergies.strip()),
                           "allergy_groups_excluded": sorted(allergy_tags),
                           "missing_profile_fields": missing, "unverified_results": unverified},
        "findings": [f for f in findings.values() if f["direction"]],
        "alerts": alerts,
        "diet": {"items": diet, "meal_plan": _meal_plan(ctx, blocking)},
        "lifestyle": {"items": _lifestyle_items(ctx)},
        "disclaimer": DISCLAIMER,
    }
