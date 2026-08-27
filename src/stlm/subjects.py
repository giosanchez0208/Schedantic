"""What goes on the calendar: the subject half of the surface inventory.

Split out of lexicon.py because it is large, and large is the point. The
generator's whole subject vocabulary used to be 39 activities and 19 event
nouns -- 58 concepts -- against 770 time surfaces and 79 relative-date surfaces.
The temporal side was fifteen times richer than the subject side, and the model
learned the obvious lesson from that: anything it does not recognise is probably
temporal.

That is why "walk the dog 8am" tagged `walk` as RECUR. The word had never once
appeared in a title during training, and position 0 of a generated line is
usually a day code. `run` became DATE and `cat` became DATE by the same route.

So the fix is not more parameters, it is a subject vocabulary wide enough that
memorising it stops being a viable strategy. A model that cannot memorise the
nouns has to learn the structure instead, which is the thing we actually want.

Two shapes live here, and the second one is the one that was missing entirely:

  CONCEPTS   canonical concept -> every way of writing it. Same left-to-right /
             right-to-left contract as lexicon.py: normalization table for the
             parser, realization table for the generator. Synonyms come free.

  VERB_OBJECT  "walk the dog", "pay the electric bill". A title can be a whole
             verb phrase, not just a noun. Nothing in the old inventory had this
             shape, so nothing in training did either.

NOTE ON PROVENANCE. These are written from general knowledge of what people
schedule. They are deliberately NOT lifted from the 290 dev summary words that
the coverage probe reported missing -- copying the evaluation set's vocabulary
into the generator would raise the dev score without teaching the model
anything, and test would find out. Coverage against dev is measured afterwards
as a diagnostic, and reported as a partial number rather than engineered to 100%.
"""

from __future__ import annotations

# --- subjects as concept -> surfaces ----------------------------------------

CONCEPTS: dict[str, list[str]] = {
    # --- errands and shopping ------------------------------------------------
    "grocery": ["grocery run", "groceries", "grocery shopping", "supermarket run",
                "market run", "palengke run", "food shopping", "weekly groceries",
                "grocery trip", "supermarket"],
    "market": ["wet market", "palengke", "the market", "talipapa", "farmers market"],
    "pharmacy": ["pharmacy", "drugstore run", "botika", "pick up meds",
                 "prescription pickup", "refill meds", "mercury drug"],
    "hardware": ["hardware store", "hardware run", "ace hardware", "get supplies"],
    "post": ["post office", "mail the package", "send the parcel", "lbc drop off",
             "courier drop off", "ship the order"],
    "bank_errand": ["bank", "bank errand", "deposit the check", "atm run",
                    "bank appointment", "open the account"],
    "package": ["pick up the package", "collect the parcel", "claim the delivery",
                "get the shopee order", "lazada pickup"],
    "returns": ["return the order", "exchange the item", "process the return"],

    # --- pets ----------------------------------------------------------------
    "dog_walk": ["walk the dog", "dog walk", "walk bruno", "take the dog out",
                 "morning dog walk", "walk the pup"],
    "pet_feed": ["feed the dog", "feed the cat", "feed the fish", "feed the pets",
                 "pet feeding"],
    "vet": ["vet", "vet appointment", "vet checkup", "take the dog to the vet",
            "annual shots", "rabies shot", "deworming", "grooming appointment"],
    "pet_groom": ["dog grooming", "pet grooming", "bath the dog", "nail trim"],
    "litter": ["clean the litter box", "change the litter"],

    # --- household -----------------------------------------------------------
    "laundry": ["laundry", "laundry day", "do the laundry", "wash clothes",
                "labada", "drop off laundry", "pick up laundry", "fold the laundry"],
    "cleaning": ["clean the room", "general cleaning", "deep clean", "vacuum",
                 "mop the floors", "tidy up", "clean the kitchen", "linis bahay"],
    "dishes": ["do the dishes", "wash the dishes", "dish duty"],
    "trash": ["take out the trash", "garbage day", "bring out the bins",
              "segregate the trash"],
    "plants": ["water the plants", "repot the plants", "garden day", "trim the hedge",
               "mow the lawn", "water the garden"],
    "bedding": ["change the sheets", "wash the beddings", "flip the mattress"],
    "groceries_home": ["meal prep", "prep lunches", "batch cook", "cook adobo",
                       "bake bread", "make sinigang", "sunday cooking"],

    # --- health and admin ----------------------------------------------------
    "dentist": ["dentist", "dental cleaning", "dentist appointment", "tooth extraction",
                "braces adjustment", "dental checkup"],
    "doctor": ["doctor appointment", "checkup", "annual physical", "consultation",
               "follow up", "clinic visit", "medical checkup", "opd visit"],
    "eye": ["eye exam", "optometrist", "get new glasses", "contact lens fitting"],
    "lab_test": ["blood test", "lab work", "fasting blood sugar", "x ray",
                 "urinalysis", "cbc", "ultrasound"],
    "vaccine": ["flu shot", "booster shot", "vaccination", "immunization"],
    "therapy_health": ["therapy", "counseling session", "physical therapy",
                       "rehab session", "psych appointment"],
    "meds": ["take vitamins", "take meds", "morning meds", "maintenance meds",
             "insulin", "supplements"],

    # --- personal care -------------------------------------------------------
    "haircut": ["haircut", "barber", "salon appointment", "hair color", "trim",
                "gupit"],
    "nails": ["manicure", "pedicure", "mani pedi", "nail appointment"],
    "massage": ["massage", "spa day", "hilot", "back massage"],

    # --- finance and paperwork ----------------------------------------------
    "bills": ["pay the electric bill", "pay meralco", "water bill", "pay the bills",
              "internet bill", "settle the bills", "pay rent", "rent due"],
    "loan": ["loan payment", "credit card due", "card payment", "amortization"],
    "tax": ["file the taxes", "bir filing", "quarterly filing", "submit itr"],
    "renewal": ["renew the license", "passport renewal", "renew the registration",
                "nbi clearance", "barangay clearance", "renew the permit",
                "car registration"],
    "insurance": ["insurance payment", "policy renewal", "philhealth", "sss payment",
                  "pag ibig"],
    "budget": ["budget review", "track expenses", "reconcile the books",
               "monthly budget"],

    # --- transport and vehicle ----------------------------------------------
    "car_service": ["car service", "oil change", "change oil", "car wash",
                    "tire rotation", "pms", "bring the car to casa", "aircon cleaning"],
    "commute": ["leave for work", "catch the bus", "airport run", "pick up from school",
                "drop off at school", "fetch the kids", "school run"],
    "flight": ["flight", "check in for the flight", "airport transfer", "board the ferry",
               "bus terminal", "catch the train"],

    # --- family and social ---------------------------------------------------
    "birthday": ["birthday", "birthday party", "birthday dinner", "kaarawan",
                 "surprise party"],
    "anniversary": ["anniversary", "wedding anniversary", "monthsary"],
    "visit": ["visit lola", "visit the grandparents", "family visit", "home visit",
              "visit the cemetery", "hospital visit"],
    "dinner_out": ["dinner", "dinner out", "family dinner", "date night", "lunch out",
                   "merienda", "brunch", "salu salo", "handaan"],
    "coffee": ["coffee", "coffee catch up", "kape", "coffee with the gang",
               "catch up over coffee"],
    "movie": ["movie night", "cinema", "watch the movie", "movie date", "watch party"],
    "hangout": ["hang out", "gimik", "inuman", "game night", "board game night",
                "karaoke", "videoke"],
    "wedding": ["wedding", "wedding rehearsal", "reception", "engagement party",
                "bridal shower"],
    "funeral": ["wake", "burial", "lamay", "memorial service"],
    "reunion": ["reunion", "class reunion", "family reunion", "homecoming"],

    # --- fitness and sport ---------------------------------------------------
    "gym": ["gym", "gym session", "workout", "leg day", "push day", "pull day",
            "lifting", "weights", "training session"],
    "run": ["run", "morning run", "jog", "jogging", "5k run", "long run", "takbo"],
    "swim": ["swimming", "swim practice", "lap swim", "pool session"],
    "ballgame": ["basketball", "pickup ball", "badminton", "volleyball", "football",
                 "tennis", "table tennis", "pickleball", "futsal"],
    "yoga": ["yoga", "yoga class", "pilates", "zumba", "aerobics", "stretching"],
    "cycling": ["bike ride", "cycling", "spin class", "long ride"],
    "martial": ["boxing", "muay thai", "jiu jitsu", "karate", "taekwondo", "sparring",
                "arnis"],
    "walk_exercise": ["walk", "evening walk", "walk the loop", "hike", "trek",
                      "morning walk"],

    # --- faith ---------------------------------------------------------------
    "mass": ["mass", "sunday mass", "misa", "church", "service", "worship service",
             "anticipated mass"],
    "prayer": ["prayer meeting", "bible study", "rosary", "novena", "devotion",
               "evening prayers", "small group"],
    "church_duty": ["choir practice", "lector duty", "usher duty", "youth ministry",
                    "servers meeting"],

    # --- hobbies and creative ------------------------------------------------
    "music_practice": ["guitar lesson", "piano practice", "band rehearsal", "drum lesson",
                       "voice lesson", "violin practice", "jam session"],
    "art": ["painting", "sketching", "pottery class", "art class", "mini painting",
            "calligraphy", "craft night"],
    "photo": ["photo shoot", "photowalk", "edit the photos", "shoot the product"],
    "writing": ["writing session", "journal", "blog post", "draft the chapter"],
    "reading": ["book club", "reading time", "finish the book"],
    "gaming": ["dnd session", "one shot", "raid night", "tournament", "ranked grind",
               "game session", "campaign night"],
    "garden_hobby": ["plant shopping", "propagate cuttings", "plantito duties"],

    # --- work ----------------------------------------------------------------
    "meeting": ["meeting", "sync", "standup", "1on1", "one on one", "check in",
                "catch up", "huddle", "touch base", "alignment call"],
    "review_work": ["performance review", "sprint planning", "retro", "retrospective",
                    "sprint review", "planning session", "backlog grooming"],
    "client": ["client call", "client meeting", "demo", "pitch", "presentation",
               "site visit", "ocular", "walkthrough"],
    "interview": ["interview", "final interview", "panel interview", "screening call",
                  "job interview"],
    "deadline": ["deadline", "submission deadline", "report due", "deliverable due",
                 "cutoff", "eod deadline"],
    "shift": ["shift", "night shift", "duty", "on call", "graveyard shift",
              "opening shift", "closing shift", "work study hours"],
    "training_work": ["training", "onboarding", "orientation", "seminar", "webinar",
                      "workshop", "upskilling session"],
    "admin_work": ["file the report", "submit the timesheet", "process payroll",
                   "inventory count", "stock count", "audit"],

    # --- study ---------------------------------------------------------------
    "class": ["class", "lecture", "lab", "laboratory", "recitation", "tutorial",
              "discussion", "seminar"],
    "exam": ["exam", "quiz", "midterms", "finals", "long test", "periodical",
             "prelims", "departmental exam"],
    "study": ["study group", "review session", "study session", "group study",
              "cram session", "tutoring"],
    "thesis": ["thesis defense", "thesis consultation", "capstone defense",
               "proposal defense", "final defense", "adviser meeting"],
    "school_admin": ["enrollment", "registration", "advising", "clearance",
                     "graduation rehearsal", "orientation day"],
    "project": ["group project", "project meeting", "case study", "practicum",
                "ojt", "internship"],

    # --- community and civic -------------------------------------------------
    "volunteer": ["volunteer", "outreach", "feeding program", "relief packing",
                  "beach cleanup", "tree planting", "community service"],
    "meeting_civic": ["barangay meeting", "hoa meeting", "condo association meeting",
                      "pta meeting", "general assembly"],
    "donate": ["blood donation", "donation drive", "give blood"],

    # --- home projects -------------------------------------------------------
    "repair": ["fix the sink", "repair the door", "call the plumber", "electrician",
               "aircon cleaning", "pest control", "termite treatment"],
    "move": ["move out", "move in", "pack the boxes", "turnover", "house viewing",
             "meet the landlord"],
}

# --- titles that are a whole verb phrase ------------------------------------
# The shape the old inventory had none of. "walk the dog" is a title; nothing in
# training ever showed one, so a leading verb read as a day code.

VERBS: list[str] = [
    "walk", "feed", "water", "call", "text", "email", "message", "pay", "buy",
    "pick up", "drop off", "fetch", "return", "renew", "submit", "send", "book",
    "confirm", "cancel", "reschedule", "collect", "clean", "fix", "refill",
    "check", "review", "print", "sign", "deliver", "claim", "follow up on",
    "prepare", "pack", "unpack", "sort", "file", "update", "back up", "charge",
    "order", "reorder", "cook", "bake", "defrost", "iron", "sweep", "wash",
]

OBJECTS: list[str] = [
    "the dog", "the cat", "the plants", "the fish", "the pets",
    "mom", "dad", "lola", "the landlord", "the plumber", "the clinic",
    "the electric bill", "the water bill", "the internet bill", "the rent",
    "the kids", "the car", "the bike", "the package", "the parcel",
    "the prescription", "the laptop", "the passport", "the license",
    "the documents", "the forms", "the report", "the deck", "the invoice",
    "the receipts", "the groceries", "the laundry", "the uniform",
    "the tickets", "the reservation", "the appointment", "the order",
    "the batteries", "the aircon filter", "the water jug", "the gas tank",
]

# --- venues ------------------------------------------------------------------
# A place is part of the title (LOCATION was removed 2026-08-27), so these are
# realized inside the summary rather than as their own slot.

VENUES: list[str] = [
    "Rm 201", "Room 305", "rm201", "Room 4B", "AVR", "the gym", "the library",
    "Lab 3", "Bldg C", "Zoom", "Google Meet", "MS Teams", "online", "Discord",
    "Starbucks", "the cafe", "the coffee shop", "the field", "Court 2",
    "CS Building", "the Annex", "3rd floor", "Main Hall", "the clinic",
    "the chapel", "the parish hall", "the covered court", "the plaza",
    "the mall", "the food court", "the office", "the conference room",
    "the boardroom", "the pantry", "the rooftop", "the parking lot",
    "the barangay hall", "the health center", "the studio", "the dojo",
    "the pool", "the track oval", "the dugout", "the clubhouse",
    "the auditorium", "the multipurpose hall", "the seminar room",
    "the training room", "the workshop", "the garage", "the warehouse",
    "the stockroom", "the back office", "the front desk", "the lobby",
    "our place", "their place", "tita's house", "the condo", "the village",
]

# --- extra course-code stems -------------------------------------------------

SUBJECT_PREFIXES_EXTRA: list[str] = [
    "COMSCI", "MKTG", "MGMT", "FIN", "LAW", "MED", "NURS", "ARCH", "CE", "EE",
    "ME", "ChE", "IE", "ENTREP", "HRM", "TOUR", "COMM", "JOURN", "LIT", "THEO",
    "ETHICS", "ALG", "CALC", "TRIG", "GEOM", "ZOOL", "BOT", "MICRO", "ORGCHEM",
    "PHYSED", "ROTC", "CWTS", "MUSIC", "DRAW", "DESIGN", "PROG", "DBMS", "NET",
]

EXTRA_FIRST_NAMES: list[str] = [
    "Aliyah", "Bianca", "Cedric", "Dara", "Enzo", "Faye", "Gio", "Hazel",
    "Iggy", "Jonas", "Kiana", "Lorenzo", "Mika", "Nico", "Oyen", "Pia",
    "Quennie", "Rafa", "Shanti", "Trina", "Ulysses", "Via", "Wilmer", "Yana",
    "Zaldy", "Arjay", "Bem", "Chichi", "Dodong", "Emman", "Ferdie", "Glenda",
    "Hilda", "Ismael", "Jhun", "Karla", "Lito", "Mila", "Noel", "Odette",
    "Popoy", "Rhea", "Sonny", "Tikoy", "Ubaldo", "Vilma", "Weng", "Yolly",
    "Zeny", "Kuya", "Tita", "Tito", "Lolo", "Doc", "Coach", "Sir", "Ma'am",
    "the team", "the group", "the committee", "my sup", "my adviser",
    "the client", "the barkada", "the fam",
]


# --- time-of-day surfaces ----------------------------------------------------
# The generator emitted a time-of-day TSTART on 0.24% of lines against 3.2% in
# the human corpus, a 13x shortfall, which is why "walk in the morning" and
# "Tea time, noon" fell over. normalize.py already maps these words to symbols
# in the parsing direction; this is the same table read the other way.

TOD_SURFACES: dict[str, list[str]] = {
    "TOD:DAWN": ["dawn", "at dawn", "before sunrise", "madaling araw",
                 "first thing", "crack of dawn"],
    "TOD:MORNING": ["morning", "in the morning", "mornings", "early morning",
                    "am", "AM", "first thing in the morning", "umaga"],
    "TOD:NOON": ["noon", "midday", "at noon", "lunchtime", "tanghali", "high noon"],
    "TOD:AFTERNOON": ["afternoon", "in the afternoon", "afternoons",
                      "late afternoon", "pm", "hapon"],
    "TOD:EVENING": ["evening", "in the evening", "evenings", "early evening",
                    "dusk", "gabi", "after dinner"],
    "TOD:NIGHT": ["night", "nights", "tonight", "at night", "late night",
                  "before bed", "evening"],
}


# --- date surfaces the generator was missing ---------------------------------
# lexicon.REL_DATES only ever held the 17 relative symbols. Every other date
# family -- month-name dates, ordinal day-of-month, bare months, holidays --
# looked up as None, so the chunk was never appended and the row shipped with a
# date in L2 that appeared nowhere in the text. 17.7% of balanced rows.

ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd", 21: "st", 22: "nd", 23: "rd", 31: "st"}


def ordinal(d: int) -> str:
    return f"{d}{ORDINAL_SUFFIX.get(d, 'th')}"


# How an ordinal day-of-month gets written. "%s" takes the ordinal.
DOM_TEMPLATES: list[tuple[str, float]] = [
    ("the %s", 5.0), ("on the %s", 4.0), ("every %s", 2.0), ("%s", 2.0),
    ("by the %s", 1.5), ("the %s of the month", 1.0),
]

# How a month-and-day gets written. "%(mon)s" and "%(day)s".
MD_TEMPLATES: list[tuple[str, float]] = [
    ("%(mon)s %(day)s", 8.0), ("%(mon)s. %(day)s", 2.0),
    ("%(day)s %(mon)s", 2.0), ("on %(mon)s %(day)s", 2.0),
    ("%(mon)s %(ord)s", 3.0), ("the %(ord)s of %(mon)s", 1.0),
]

MONTH_ONLY_TEMPLATES: list[tuple[str, float]] = [
    ("in %(mon)s", 3.0), ("%(mon)s", 3.0), ("sometime in %(mon)s", 1.0),
    ("early %(mon)s", 1.0), ("by %(mon)s", 1.5),
]
