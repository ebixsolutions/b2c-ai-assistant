"""Gemini / Vertex AI service — ports GeminiService.php to Python.

Uses google-auth for OAuth2 token and calls the Vertex AI REST API directly.
All public functions return dicts with a 'code' key (0 = success).
"""
import os
import re
import json
import logging

import requests
import urllib3
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("b2c.gemini")

_PROJECT_ID = os.getenv("PROJECT_ID", "vertex-ai-api-491406")
_LOCATION   = os.getenv("LOCATION",   "us-central1")
_MODEL      = os.getenv("MODEL",       "gemini-2.5-flash")

# ── Data maps (module-level constants) ─────────────────────────────────────

CATEGORY_MAP = {
    "skincare":      "Skincare & Cosmetics",
    "hair_care":     "Hair Care & Styling",
    "health_beauty": "Health & Body Care",
    "supplements":   "Supplements & Nutrition",
    "fragrance":     "Fragrance & Perfume",
    "fashion":       "Women's Fashion & Apparel",
    "mens_fashion":  "Men's Fashion",
    "sneakers":      "Sneakers & Streetwear",
    "jewellery":     "Jewellery & Accessories",
    "bags":          "Bags & Luggage",
    "electronics":   "Consumer Electronics & Gadgets",
    "smart_home":    "Smart Home & IoT",
    "gaming":        "Gaming & PC Peripherals",
    "home_living":   "Home Décor & Furniture",
    "kitchen":       "Kitchen & Cooking",
    "cleaning":      "Cleaning & Organisation",
    "food_beverage": "Food & Snacks",
    "beverages":     "Beverages & Drinks",
    "coffee_tea":    "Coffee & Tea",
    "sports":        "Sports & Fitness",
    "outdoor":       "Outdoor & Adventure",
    "activewear":    "Activewear & Sportswear",
    "baby_kids":     "Baby & Kids",
    "pets":          "Pet Products",
    "automotive":    "Automotive & Car Accessories",
    "ecommerce":     "General Ecommerce",
    "general":       "General Advertising",
}

ARCHETYPE_KEY_MAP = {
    "skincare":      "skincare",
    "hair_care":     "hair_care",
    "health_beauty": "health_beauty",
    "supplements":   "supplements",
    "fragrance":     "fragrance",
    "fashion":       "fashion",
    "mens_fashion":  "fashion",
    "sneakers":      "fashion",
    "bags":          "fashion",
    "jewellery":     "jewellery",
    "electronics":   "electronics",
    "smart_home":    "electronics",
    "gaming":        "gaming",
    "home_living":   "home_living",
    "kitchen":       "food_beverage",
    "cleaning":      "cleaning",
    "food_beverage": "food_beverage",
    "beverages":     "food_beverage",
    "coffee_tea":    "coffee_tea",
    "sports":        "sports",
    "outdoor":       "sports",
    "activewear":    "activewear",
    "baby_kids":     "baby_kids",
    "pets":          "pets",
    "automotive":    "automotive",
    "ecommerce":     "ecommerce",
    "general":       "general",
}

ARCHETYPE_MAP = {
    "fashion": {
        "archetype":  "GRWM (Get Ready With Me) / Outfit Transformation",
        "psychology": "Shoppers buy identity and aspiration. They want to SEE themselves wearing it. Fast beat-sync cuts, movement shots, and a before/after styling moment drive click-through.",
        "hook":       "Avatar in a casual or neutral state in frame 1, then reaches for the product — transformation begins within the first 2 seconds.",
        "story_arc":  "Casual starting state → @Image1 reaches for @Image2 → Styled in/with the product → Confident reveal moment (mirror, turn, or walk toward camera) → CTA.",
        "visuals":    "Mirror reflection shots, fabric texture macro close-ups, 360° rotation while wearing, multiple angles showing fit and movement, warm-toned room or outdoor golden-hour light.",
    },
    "health_beauty": {
        "archetype":  "Sensory Journey or Expert Endorsement",
        "psychology": "Buyers need desire OR trust. Skincare/body products → sensory (make them feel the texture on their skin). Supplements/health devices → credibility (expert demonstrates with confidence).",
        "hook":       "Extreme macro close-up of skin or hair BEFORE → the product (@Image2) gliding into frame → first-contact application moment.",
        "story_arc":  "Problem state (dull skin, discomfort) → @Image2 introduced with hero ingredient close-up → @Image1 applying product → visible glow/transformation → CTA.",
        "visuals":    "Macro skin/hair texture, slow-motion cream or liquid application, steam or micro-bubble effects, soft warm backlight creating a skin glow, before/after comparison implied through lighting shift.",
    },
    "electronics": {
        "archetype":  "Unboxing Ritual + Feature Showcase",
        "psychology": "Buyers buy discovery and status. The unboxing IS the product experience. Feature callouts and spec overlays build confidence before purchase.",
        "hook":       "Box lid lifting or device powering on with a light-flash reveal of @Image2 — dramatic and satisfying.",
        "story_arc":  "Packaging reveal → Key feature 1 close-up with on-screen text callout → Feature 2 in real-use context → @Image1 reaction (impressed, satisfied) → CTA.",
        "visuals":    "Clean minimalist backgrounds (white or near-black), text spec overlays, slow unboxing reveal, screen or LED glow effects, @Image1 holding device toward camera.",
    },
    "sports": {
        "archetype":  "Performance Proof / In-Action Demonstration",
        "psychology": "Buyers buy capability and the aspiration to achieve. Show the product PERFORMING at its best — not on a shelf. Let them imagine the result.",
        "hook":       "@Image1 already mid-action in frame 1 (mid-rep, mid-stride, mid-movement) — @Image2 is in active use from the first second.",
        "story_arc":  "Peak action moment → Pull back to show @Image2 in full context → Close-up of key product feature (grip, material, mechanism) → @Image1 finishing strong or achieving result → CTA.",
        "visuals":    "Dynamic low angles, fast cuts, effort close-ups (grip, sweat, focus), high-contrast dramatic lighting, speed ramp or slow-motion on key action moment.",
    },
    "home_living": {
        "archetype":  "Lifestyle Integration or Feature Reveal",
        "psychology": "Buyers need to mentally place the product in their home. Either show it in a styled lifestyle scene (family using it, friends gathering around it) OR do a feature reveal (foldable, expandable, hidden compartment).",
        "hook":       "@Image2 placed in a beautifully styled room setting — lighting and styling that makes the viewer want to live there.",
        "story_arc":  "Product in styled home → Detail close-up of material or key feature → @Image1 or family naturally using it → Payoff lifestyle moment → CTA.",
        "visuals":    "Warm interior lighting, styled props and home accessories, slow reveal panning shots, material/texture macro close-ups, golden-hour window light for warmth.",
    },
    "food_beverage": {
        "archetype":  "Appetite Appeal + Preparation Ritual",
        "psychology": "Buyers buy the craving AND the ritual. The act of preparation is itself the experience. Texture, colour, steam, condensation, and the first-bite/sip moment are what trigger desire.",
        "hook":       "Hero shot of @Image2 at its most visually irresistible — bubbles rising, steam curling, condensation dripping, vivid saturated colour.",
        "story_arc":  "Product beauty shot → Key ingredient or preparation step shown → The consumption moment (pour, bite, sip) → @Image1 reaction of delight → CTA.",
        "visuals":    "Macro food photography style, slow-pour shots, ingredients falling into frame, steam and condensation, vibrant saturated colours, extreme close-up of texture on first contact.",
    },
    "ecommerce": {
        "archetype":  "Trust-Building UGC Product Showcase",
        "psychology": "General e-commerce buyers need credibility and clarity. Authentic avatar demonstration with multiple product angles builds trust. UGC aesthetic creates relatability.",
        "hook":       "@Image1 holding @Image2 up directly toward camera in a natural, relatable way — like a friend showing you something they love.",
        "story_arc":  "@Image1 introduces @Image2 conversationally → Multiple product angles → Key benefit in real-use context → Social-proof feel → CTA.",
        "visuals":    "Natural room or outdoor lighting, handheld UGC aesthetic, direct eye contact with camera, @Image2 shown from 2-3 angles, clean and uncluttered background.",
    },
    "general": {
        "archetype":  "Product Hero Showcase",
        "psychology": "Let the product speak for itself with premium cinematography. Clean, confident, aspirational.",
        "hook":       "@Image2 displayed prominently in the opening frame with dramatic directional lighting.",
        "story_arc":  "Hero product reveal → Feature detail close-up → @Image1 endorsement → CTA.",
        "visuals":    "Clean neutral backgrounds, dramatic single-source lighting, slow cinematic push-in, @Image1 with confident direct-camera delivery.",
    },
    "skincare": {
        "archetype":  "Skin Ritual & Transformation Journey",
        "psychology": "Skincare buyers invest in identity and self-care. They want to SEE texture, feel the ritual, and believe in the result. Sensory cues (serum drop, cream absorption, dewy glow) and visual transformation drive purchase more than ingredient claims alone.",
        "hook":       "Extreme macro close-up of product texture or a serum drop on skin — the formulation IS the hook. Quality is felt before it is explained.",
        "story_arc":  "Skin imperfection or dryness shown on @Image1 → @Image2 introduced with texture hero shot → Slow-motion application on skin → Glowing, transformed result → CTA.",
        "visuals":    "Macro skin and product texture close-ups, slow-motion serum or cream application, dewy glow backlight, steam or micro-bubble effects, soft warm backgrounds, before/after implied through lighting shift.",
    },
    "hair_care": {
        "archetype":  "Hair Transformation & Confidence Reveal",
        "psychology": "Hair buyers buy their best hair day — confidence, shine, and the result of a great routine. Before/after contrast is hugely powerful. The ritual (wash, condition, style) is aspirational.",
        "hook":       "@Image1's hair in its 'before' state (flat, frizzy, dry, or undone) — @Image2 enters frame as the solution within the first 2 seconds.",
        "story_arc":  "Hair problem shown (frizz, dryness, damage, flatness) → @Image2 applied in ritual → Transformation process → Confident reveal: @Image1 with healthy, glossy, styled hair → CTA.",
        "visuals":    "Slow-motion hair movement and flow, product dispensing close-ups, hair strand macro texture, glossy shine in warm backlight, before/after through lighting and colour shift.",
    },
    "supplements": {
        "archetype":  "Credibility, Results & Lifestyle Proof",
        "psychology": "Supplement buyers are skeptics first. Clinical credibility, real visible results, and an authoritative relatable spokesperson are the primary conversion drivers. Show the lifestyle outcome, not just the product.",
        "hook":       "@Image1 in a setting that signals credibility and results (gym post-workout, kitchen, outdoors, looking energised) — the benefit is already visible in their state.",
        "story_arc":  "Result state shown on @Image1 → @Image2 introduced as the reason → Key benefit, ingredient, or format shown simply → Personal endorsement from @Image1 → CTA.",
        "visuals":    "Clean clinical or active-lifestyle environments, confident direct-camera delivery, ingredient or label close-ups, clean uncluttered backgrounds that convey trust and quality.",
    },
    "fragrance": {
        "archetype":  "Sensory Emotion & Identity Signature",
        "psychology": "Fragrance buyers purchase a feeling, an identity, a memory — not a scent through a screen. Sell the emotion, the aspiration, and the character of the person who wears it. Cinematic and emotional beats outperform rational claims.",
        "hook":       "@Image1 in a cinematic mood-heavy frame — atmospheric, dramatic, feeling-forward. The emotion of the fragrance IS the hook from frame 1.",
        "story_arc":  "Atmospheric mood-setting scene → @Image2 revealed in cinematic hero shot → @Image1 applying with a meaningful expression → Emotional payoff: confidence, mystery, or allure projected → CTA.",
        "visuals":    "Film-grade cinematic look, warm/cool tones matching scent character, slow-motion fabric or hair movement, extreme close-up of bottle artistry and light refraction, atmospheric light flares or fog.",
    },
    "jewellery": {
        "archetype":  "Luxury Close-Up & Emotional Gift Story",
        "psychology": "Jewellery buyers are motivated by beauty (macro triggers desire), occasion (gift, milestone, self-reward), and the feeling of wearing something precious. Craftsmanship close-ups sell quality no spec sheet can convey.",
        "hook":       "Extreme macro of @Image2 — light catching the stone, metal texture detail, or intricate setting. The jewellery alone carries the opening frame.",
        "story_arc":  "Jewellery macro beauty shot → @Image1 putting it on or receiving it → Worn on the body (wrist, neck, hand) with a joyful expression → Product detail close-up again → CTA.",
        "visuals":    "Macro jewellery photography with light sparkle and reflection, clean dark or cream backgrounds, wrist/neck/hand worn shots, emotional expression on @Image1, ultra-sharp focus on craftsmanship detail.",
    },
    "gaming": {
        "archetype":  "Hype, Performance & Community Proof",
        "psychology": "Gamers buy performance, identity, and status within their community. High-energy reaction footage, peak-performance shots, spec callouts, and streamer-style authenticity drive desire more than polished production.",
        "hook":       "High energy from frame 1 — @Image1 mid-reaction (eyes wide, leaning in) OR @Image2 in a dramatic setup shot with RGB glow, speed lines, or dynamic composition.",
        "story_arc":  "Peak gameplay or reaction moment → @Image2 shown in active use or detail → Spec overlay or key performance benefit → @Image1 reaction of awe or satisfaction → CTA.",
        "visuals":    "Dynamic camera angles, RGB lighting effects, screen glow in dark environment, on-screen spec text callouts, fast-cut editing energy, dark gaming-room atmosphere, high-contrast dramatic lighting.",
    },
    "cleaning": {
        "archetype":  "Before/After Satisfaction & Effortless Clean",
        "psychology": "Cleaning product buyers are motivated by the RELIEF of a problem solved. The dirtier and more visually satisfying the clean reveal, the stronger the conversion. Instant visible results eliminate all doubt.",
        "hook":       "The 'before' state in frame 1 — a visible mess, stain, or dirty surface. The problem must be undeniable and immediately relatable.",
        "story_arc":  "Dirty/messy state clearly shown → @Image2 applied with minimal effort → Cleaning in progress (satisfying close-up) → Spotless, gleaming result → @Image1 satisfied reaction → CTA.",
        "visuals":    "Before/after contrast shots, spray and foam application macro close-ups, gleaming clean surface reveal, bright clean lighting for the result, close-up of the cleaning action in progress.",
    },
    "coffee_tea": {
        "archetype":  "Morning Ritual & Sensory Escape",
        "psychology": "Coffee and tea buyers are buying a ritual, not just a drink. The preparation IS the product experience. Sensory details (steam, pour, aroma suggested visually) and the emotional feeling of the first sip drive desire over every rational claim.",
        "hook":       "The most sensory moment possible — steam curling from a cup, a slow pour, condensation on a cold glass. Immediate sensory and mood appeal from frame 1.",
        "story_arc":  "Sensory preparation ritual → @Image2 in hero ingredient or packaging shot → The pour or brew moment → @Image1 first sip with genuine reaction → CTA.",
        "visuals":    "Close-up pours with steam and vapour, golden backlight through liquid, cosy morning environment (warm tones, natural window light), hands wrapped around a cup, macro coffee grounds or tea leaves.",
    },
    "activewear": {
        "archetype":  "Movement Showcase & Body Confidence",
        "psychology": "Activewear buyers are buying how it looks in motion AND how it makes them feel. Flattering fit while moving, fabric performance (stretch, texture, design), and aspirational body confidence drive purchase.",
        "hook":       "@Image1 mid-movement wearing @Image2 — mid-stretch, mid-stride, mid-pose. Fabric performance and flattering fit visible from the first second.",
        "story_arc":  "Dynamic movement shot showing @Image2 in motion → Fabric close-up during stretch (texture, elasticity, detail) → @Image1 from multiple angles showing full outfit → Confidence reveal (mirror or direct camera) → CTA.",
        "visuals":    "Studio or gym lighting flattering the fabric, slow-motion movement shots, fabric texture close-ups during stretch, multiple angles showing cut and fit, clean high-contrast lighting.",
    },
    "baby_kids": {
        "archetype":  "Safety, Trust & Parental Joy",
        "psychology": "Parents buy safety first and joy second. Every purchase is filtered through 'is this safe for my child?' — credibility and gentleness are paramount. Authentic parent-child moments trigger purchase more than any feature callout.",
        "hook":       "A genuine, warm parent-child moment with @Image2 naturally present — safety and joy are visible immediately without needing to be stated.",
        "story_arc":  "Parent-child bonding moment → @Image2 introduced naturally in context of real use → Key safety or quality feature shown simply → Joyful, reassuring result → CTA.",
        "visuals":    "Warm soft natural lighting, genuine child reactions, parent holding or using @Image2 with the child, clean safe-looking home environments, pastel or natural colour tones.",
    },
    "pets": {
        "archetype":  "Owner-Pet Bond & Happy Pet Proof",
        "psychology": "Pet owners buy from both rational need (health, safety) and emotional desire (making their pet happy). A happy pet reaction or owner delight moment is the single strongest conversion driver — authenticity is everything.",
        "hook":       "The pet as the star from frame 1 — an excited reaction, playful behaviour, or irresistibly cute moment. @Image2 enters as the clear cause of the happiness.",
        "story_arc":  "Pet behaviour or need shown → @Image2 introduced → Pet interacting with or visibly benefiting from @Image2 → Owner's warm, delighted reaction → CTA.",
        "visuals":    "Eye-level pet camera angles, natural home environments, genuine unscripted-feeling moments, warm lighting, owner-pet interaction shots, close-up of pet enjoying the product.",
    },
    "automotive": {
        "archetype":  "Power Reveal & Lifestyle Upgrade",
        "psychology": "Automotive product buyers buy either performance (specs, capability, protection) or pride (looking good, feeling status). Dramatic reveals, close-up detail shots, and the transformation of the vehicle drive desire.",
        "hook":       "The vehicle or @Image2 in a dramatic environment from frame 1 — cinematic lighting, product applied in a satisfying close-up, or a dramatic low-angle reveal shot.",
        "story_arc":  "Vehicle or product establishing shot → @Image2 in active use close-up (detail, application, function) → The result (shine, protection, power, clean finish) → @Image1 with the vehicle satisfied → CTA.",
        "visuals":    "Automotive cinematic lighting (golden hour, studio spot), product application close-ups, moving or static vehicle detail shots, dramatic low angles, reflection shots on clean bodywork.",
    },
}

DIALOGUE_STYLE_MAP = {
    "health_beauty": {
        "pov":     "first-person sensory testimonial — the avatar sharing their personal experience",
        "style":   "Confiding to a friend after their routine. Reference the specific sensation: texture, warmth, glow, relief. Present tense.",
        "example": '"After my run, this is the only thing my skin actually drinks in."',
    },
    "fashion": {
        "pov":     "first-person transformation moment — the avatar reacting to how they feel wearing it",
        "style":   "Capture the emotional shift, not a product description. Express confidence or identity found.",
        "example": '"I put it on and something just clicked — this is me."',
    },
    "sports": {
        "pov":     "the AVATAR is speaking directly to the viewer — like an athlete coaching or challenging you, NOT a narrator",
        "style":   "Short punchy sentences. The avatar challenges the viewer from personal experience. First or second person. Sounds like something a real athlete would say, not a voiceover actor.",
        "example": '"This is how I play every single game — nothing else comes close."',
    },
    "electronics": {
        "pov":     "first-person discovery — the avatar reacting to a key feature or benefit",
        "style":   'Convey the "aha moment". Mention one specific feature, not a generic statement.',
        "example": '"I didn\'t think earbuds could actually block out the whole city."',
    },
    "home_living": {
        "pov":     "first-person aspiration — the avatar expressing how it changed their space or daily life",
        "style":   "Warm, personal, ownership-focused. Make the viewer picture it in their own home.",
        "example": '"Every morning I wake up and this is the first thing I see — and I love it."',
    },
    "food_beverage": {
        "pov":     "first-person sensory craving — the avatar in the moment of consuming or anticipating",
        "style":   "Evoke taste, smell, texture. Write so the viewer's mouth waters. Present-tense immediacy.",
        "example": '"That first sip — every single time, it hits different."',
    },
    "ecommerce": {
        "pov":     "first-person direct testimonial — UGC style, like a friend talking to camera",
        "style":   "Casual, relatable, direct. Mention the product honestly. Avoid polished ad-speak.",
        "example": '"I was skeptical but honestly — I use this every single day now."',
    },
    "general": {
        "pov":     "second-person direct address — speaking to the viewer",
        "style":   "Confident and clear. Product benefit stated with personal relevance.",
        "example": '"This is the one thing you\'ll wish you started using sooner."',
    },
    "skincare": {
        "pov":     "first-person sensory ritual — narrating what they feel on their skin as they apply the product",
        "style":   "Intimate, close-to-camera confessional. Reference the specific sensation: texture, absorption, warmth, glow. Present-tense immediacy, like sharing a skincare secret.",
        "example": '"I press it in and my skin just drinks it up — every single morning."',
    },
    "hair_care": {
        "pov":     "first-person transformation testimonial — reacting to their best hair day",
        "style":   "Surprise and delight at the result. Reference the specific change: frizz gone, shine visible, softness felt. Natural, not clinical.",
        "example": '"I haven\'t had a bad hair day since I started using this."',
    },
    "supplements": {
        "pov":     "first-person credibility testimony — speaking from real personal experience and visible results",
        "style":   "Confident and direct. State one specific benefit that is personally meaningful. Avoid generic health claims — be personal and specific.",
        "example": '"Three weeks in and I genuinely feel different — energy is just on another level."',
    },
    "fragrance": {
        "pov":     "first-person emotional identity — expressing how wearing it changes how they feel or how others react",
        "style":   "Mysterious, evocative, emotional. Reference the feeling or reaction it creates, not the scent notes. Short and memorable.",
        "example": '"People always ask what I\'m wearing — and I never tell them."',
    },
    "jewellery": {
        "pov":     "first-person emotional ownership — expressing what the piece means or how wearing it feels",
        "style":   "Warm and personal. Reference the feeling of wearing it, the occasion it marks, or the reaction it gets. Avoid describing the product — describe the feeling.",
        "example": '"Every time I wear this, I feel like I can walk into any room."',
    },
    "gaming": {
        "pov":     "first-person community voice — speaking to other gamers as a peer, not over-explaining",
        "style":   "Short, punchy, community-coded. Reference the specific performance edge. Should sound like something a real gamer would say in a stream or clip.",
        "example": '"This is the only setup I\'ve used that actually keeps up with me."',
    },
    "cleaning": {
        "pov":     "first-person relief and satisfaction — reacting to the visible result of using the product",
        "style":   '"Look at this" energy. Short and punchy. Before/after framing in the line.',
        "example": '"I honestly thought that stain was permanent — never again."',
    },
    "coffee_tea": {
        "pov":     "first-person sensory ritual — in the moment of the first sip or the preparation",
        "style":   "Warm, slow, savouring. Evoke the taste, aroma, comfort, or ritual. Write so the viewer feels the warmth of the cup in their hands.",
        "example": '"Every morning starts here — nothing else comes close."',
    },
    "activewear": {
        "pov":     "first-person confidence and performance — expressing how the fit or fabric feels while moving",
        "style":   "Energetic and body-positive. Reference the specific feeling: support, freedom, stretch, the confidence of a great fit. In-motion energy.",
        "example": '"I forget I\'m even wearing anything — it just moves with me."',
    },
    "baby_kids": {
        "pov":     "parent-voice testimonial — speaking as a parent expressing relief, joy, or trust in the product",
        "style":   "Warm, honest, parental. Reference the child's reaction or the peace of mind it gives. Authenticity over polished ad-speak.",
        "example": '"The only one she actually lets me use without a fuss."',
    },
    "pets": {
        "pov":     "pet-owner voice — speaking about their pet with genuine love, product is the reason for the pet's happiness",
        "style":   "Warm, affectionate, genuine. Reference the pet's reaction specifically. Should feel like something you'd say to a friend about your dog or cat.",
        "example": '"The second she hears it open, she comes running — every time."',
    },
    "automotive": {
        "pov":     "first-person pride and performance — expressing satisfaction with what the product does for their vehicle",
        "style":   "Proud, confident, specific. Reference the visible result: shine, protection, performance, upgrade. Sounds like a car enthusiast speaking to their community.",
        "example": '"I\'ve tried everything — nothing comes close to what this does to the paint."',
    },
}

BGM_MAP = {
    "ambient":   "Lush ambient texture, airy and flowing — played at full, prominent volume so it is unmistakably heard on any speaker or phone; rich and immersive, fills the soundscape completely alongside the voice",
    "acoustic":  "Warm acoustic guitar, finger-picked and intimate — prominently mixed at full volume, clearly heard and felt on any device, voice and music both strong and equally present",
    "luxury":    "Elegant piano melody, unhurried and sophisticated — played at full prominent volume throughout, refined and bold, music and voice share the soundscape as confident equals",
    "corporate": "Clean motivating background track, steady mid-tempo — loud and clearly heard on any speaker, voice and music both strong, music pushes forward with confident energy",
    "emotional": "Emotional strings and piano swelling warmly — prominently loud throughout, music surges to fill every moment, voice-forward but music hits with full emotional power",
    "cinematic": "Full cinematic orchestral score, sweeping strings and rich percussion — loud and dramatic, clearly dominant on any speaker, voice and music both hit with maximum impact",
    "trendy":    "Punchy trendy pop track with thick bass and bright synth lead — bold and energetic, music as loud as the voice, beat strongly and unmistakably felt on any device",
    "upbeat":    "Hard-driving pop/electronic track — pounding kick drums, thick stacked synth bass, bright driving lead; music pushes to the foreground and stays at maximum volume throughout the entire video, driving the energy above everything else",
    "none":      "No background music",
}

VOICE_MAP = {
    "energetic_female":    "energetic, upbeat young female voice, fast-paced and enthusiastic",
    "energetic_male":      "energetic, upbeat young male voice, fast-paced and enthusiastic",
    "warm_female":         "warm, friendly female voice, natural conversational pace",
    "warm_male":           "warm, friendly male voice, natural conversational pace",
    "calm_female":         "calm, sophisticated mature female voice, slow and deliberate, conveying premium quality",
    "calm_male":           "calm, sophisticated mature male voice, slow and deliberate, conveying premium quality",
    "professional_female": "clear, professional female voice, confident and authoritative, moderate pace",
    "professional_male":   "clear, professional male voice, confident and authoritative, moderate pace",
    "playful_female":      "casual, playful young female voice, light-hearted and natural",
    "playful_male":        "casual, playful young male voice, light-hearted and natural",
    "deep_narrator":       "deep, intense male narrator voice, building tension and drama",
    "whisper_female":      "soft, intimate female voice, close and ASMR-style",
    "none":                None,
}

HOOK_MAP = {
    "UGC – Talking Head":
        "@Image1 faces camera holding @Image2, direct eye contact from frame 1 — already speaking or a half-second before they speak. No build-up, no product reveal shot, jump straight in.",
    "UGC – Funny & Relatable":
        "@Image1 in an unexpected or relatable everyday situation in frame 1 — the comedy or relatability IS the hook before the product appears.",
    "Get Ready With Me (GRWM)":
        "@Image1 at mirror or vanity in a casual, undone starting state, reaching for @Image2 — the transformation begins within the first 2 seconds.",
    "Before & After":
        "The 'before' state is shown in frame 1 — @Image1 visibly showing the problem, discomfort, or old look. No product yet.",
    "Tutorial / How-To":
        "@Image1 holds @Image2 up toward camera, ready to demonstrate. Product clearly visible and identifiable from second 1.",
    "Unboxing & First Reaction":
        "Hands on or opening the packaging of @Image2 — anticipation and discovery IS the hook. The unboxing moment starts immediately.",
    "Expert / Specialist Endorsement":
        "@Image1 in a setting that signals their authority (gym, clinic, studio, kitchen) — already engaging with @Image2 with confidence and knowledge.",
    "Problem → Solution":
        "Pain point is visible in frame 1 — @Image1 experiencing the problem, frustration, or discomfort. The problem must be immediately recognisable before any solution is shown.",
    "Emotional Storytelling":
        "@Image1 with a meaningful or emotional expression in frame 1 — feeling comes before product. The emotion draws the viewer in, product enters naturally.",
    "Flash Offer / Direct Response":
        "High energy from frame 1 — @Image1 holds @Image2 directly toward camera OR bold price/offer text overlaid immediately. Urgency is the hook.",
    "Luxury Product Reveal":
        "Extreme macro of @Image2 — material texture, surface detail, or key design element with dramatic directional lighting. Product alone in frame, no person yet. Slow and deliberate.",
    "Product Hero Showcase":
        "@Image2 in a dramatic close-up hero shot for the first 1 second ONLY — keep this short so the dialogue does not play long as narrator before the avatar appears. Then @Image1 enters frame at [1s] and picks it up or interacts with it (1-2 seconds). Then a SEPARATE dedicated timestamp immediately after: @Image1 in medium close-up, full face toward camera, animated and expressive — speaking to the viewer about the product. This speaking timestamp must be its own shot; do NOT combine the pick-up action and the speaking moment into a single timestamp. Use the exact words \"speaking to the viewer\" or \"speaking to the camera\" in that dedicated speaking timestamp. The avatar must appear on screen by [2s] at the latest — never delay their entrance beyond that.",
    "Performance / In-Action":
        "Action is ALREADY HAPPENING in frame 1 — mid-motion, mid-rep, mid-throw, mid-stride. Do NOT start before the action; start deep inside it.",
    "Lifestyle Aesthetic":
        "Aspirational environment shot — beautiful, styled setting with @Image2 placed naturally. The scene and mood are established before the avatar enters the frame.",
    "K-Beauty / Skincare Ritual":
        "Macro close-up of @Image2 texture or skin surface — sensory, product-first opening. No avatar yet. Narrator tone for the first 3 seconds.",
}

STYLE_BG_MAP = {
    "UGC – Talking Head":
        "a real casual home environment: bedroom with natural window light, bathroom vanity area, kitchen counter, or living room couch. NOT a studio set, NOT a styled luxury room. Ring light or natural window light gives that authentic phone-camera feel.",
    "UGC – Funny & Relatable":
        "a relatable everyday location (kitchen, living room, bedroom, bathroom) — feels like a real home, not a set. Natural ambient light.",
    "Get Ready With Me (GRWM)":
        "a dressing room, vanity mirror area, or well-lit bathroom — personal space that feels real and lived-in, not styled.",
    "Before & After":
        "the real-world environment where the problem naturally occurs (bathroom for skincare/hair/fragrance, kitchen for food, living room for home products).",
    "Tutorial / How-To":
        "a clear functional home surface (bathroom vanity, kitchen counter, or desk) — practical and uncluttered so the tutorial steps are visible.",
    "Unboxing & First Reaction":
        "a natural everyday surface — table, floor, or couch — that feels un-staged and authentic.",
    "Expert / Specialist Endorsement":
        "a professional environment that signals the avatar's authority (gym, clean studio, professional kitchen, outdoor active setting) — must match @Image1's apparent role.",
    "Problem → Solution":
        "the real-world location where the problem naturally occurs (bathroom for skin/hair/fragrance, living room for cleaning/home, kitchen for food/supplements).",
    "Emotional Storytelling":
        "a warm personal environment — soft natural light, a quiet home setting or outdoor space that matches the emotional tone.",
    "Flash Offer / Direct Response":
        "a clean simple background (plain colour wall or minimal home surface) — the offer and product are the focus, not the environment.",
    "Luxury Product Reveal":
        "a sleek minimal studio or upscale interior — marble or matte surfaces, dramatic single-source lighting, no clutter.",
    "Product Hero Showcase":
        "a clean neutral background (light grey, cream, or matte black) with dramatic directional lighting — professional studio aesthetic.",
    "Performance / In-Action":
        "a dynamic performance environment matching the product category (gym interior, outdoor trail, sports court, urban street) — the setting must signal peak performance.",
    "Lifestyle Aesthetic":
        "an aspirational lifestyle location (sunlit café terrace, outdoor golden-hour park, beautifully styled interior space) — atmospheric and mood-setting.",
    "K-Beauty / Skincare Ritual":
        "a soft minimal bathroom or vanity area — clean, aesthetic, product-focused with warm diffused light.",
}

CATEGORY_BG_DETAIL_MAP = {
    "skincare":      "bathroom vanity or makeup area — where a morning/evening skincare routine naturally happens",
    "hair_care":     "bathroom or dressing-table mirror area — where hair care routines take place",
    "health_beauty": "bathroom counter or bedroom dresser — where body care and grooming products live",
    "supplements":   "kitchen counter next to a glass of water, or gym bag/workout area — where supplements are actually taken",
    "fragrance":     "bedroom dresser or bathroom vanity — where fragrance is applied when getting ready",
    "fashion":       "bedroom closet area or in front of a full-length mirror — where outfit decisions happen",
    "mens_fashion":  "bedroom or hallway mirror — where a guy checks his outfit before heading out",
    "sneakers":      "hallway doorway, bedroom floor, or outdoor street step — where sneakers are put on and shown off",
    "jewellery":     "dressing table or vanity with a mirror — where accessories are put on",
    "bags":          "bedroom or hallway — where a bag is packed or picked up before going out",
    "electronics":   "desk setup, couch with a coffee table, or kitchen counter — where devices are used daily",
    "smart_home":    "living room or home office — where smart home devices are installed and used",
    "gaming":        "desk gaming setup with a monitor and RGB lighting — the authentic gamer environment",
    "home_living":   "living room, dining area, or home interior — where the décor or furniture is actually placed",
    "kitchen":       "kitchen counter or dining table — where food preparation and cooking happens",
    "cleaning":      "the dirty or messy surface being cleaned (kitchen counter, bathroom tile, floor) — problem first",
    "food_beverage": "kitchen counter or casual dining table — where food is prepared and enjoyed",
    "beverages":     "kitchen counter or casual outdoor seating — where drinks are poured and consumed",
    "coffee_tea":    "kitchen counter, breakfast nook, or a cosy couch corner — morning ritual location",
    "sports":        "gym floor, home workout area, or outdoor trail — active performance environment",
    "outdoor":       "outdoor setting — park, trail, backyard, or open road — where the activity happens",
    "activewear":    "gym interior, outdoor park, or studio mirror — where activewear is actually worn and seen in motion",
    "baby_kids":     "nursery, living room floor, or play area — where parent and child interact with the product",
    "pets":          "living room floor, backyard, or kitchen — where the pet and owner interact",
    "automotive":    "garage, driveway, or inside the car — where automotive products are used and results are visible",
    "ecommerce":     "living room or bedroom — a relatable everyday home setting",
    "general":       "living room or kitchen — a neutral, relatable home space",
}

_AVATAR_SPEAKS_STYLES = {
    "UGC – Talking Head", "UGC – Funny & Relatable",
    "Get Ready With Me (GRWM)", "Before & After",
    "Tutorial / How-To", "Unboxing & First Reaction",
    "Expert / Specialist Endorsement", "Problem → Solution",
    "Emotional Storytelling", "Flash Offer / Direct Response",
    "Product Hero Showcase",
}

_UGC_STYLES = {"UGC – Talking Head", "UGC – Funny & Relatable", "Unboxing & First Reaction"}

# ── Internal helpers ────────────────────────────────────────────────────────

def _get_access_token() -> str:
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "google-credentials.json")
    credentials = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    credentials.refresh(GoogleAuthRequest())
    return credentials.token


def _call_gemini(prompt: str, images: list[str] | None = None):
    """Call Vertex AI REST API. Returns {"code": 0, "msg": str, "raw": str|None, "usage": dict}."""
    images = images or []
    try:
        access_token = _get_access_token()
    except Exception as exc:
        logger.error("Gemini auth error: %s", exc)
        return {"code": 500, "msg": str(exc), "raw": None}

    url = (
        f"https://{_LOCATION}-aiplatform.googleapis.com/v1/projects/{_PROJECT_ID}"
        f"/locations/{_LOCATION}/publishers/google/models/{_MODEL}:generateContent"
    )

    parts: list[dict] = []
    for img_b64 in images:
        if not img_b64:
            continue
        mime_type = "image/jpeg"
        raw_b64 = img_b64
        m = re.match(r"^data:(image/\w+);base64,(.+)$", img_b64, re.DOTALL)
        if m:
            mime_type = m.group(1)
            raw_b64 = m.group(2)
        parts.append({"inline_data": {"mime_type": mime_type, "data": raw_b64}})
    parts.append({"text": prompt})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
            # These calls are single-pass extraction/classification (pick a frame, write a
            # prompt, identify segments) — not multi-step reasoning. Extended thinking was
            # measured burning ~5200 tokens (more than prompt+output combined) for ~35s per
            # call with zero quality benefit for this task shape.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=120,
            verify=False,
        )
    except requests.RequestException as exc:
        return {"code": 500, "msg": f"Connection error: {exc}", "raw": None}

    logger.info("Gemini HTTP:%d", resp.status_code)

    if resp.status_code != 200:
        try:
            err_msg = resp.json().get("error", {}).get("message", f"Gemini API error (HTTP {resp.status_code})")
        except Exception:
            err_msg = f"Gemini API error (HTTP {resp.status_code})"
        return {"code": resp.status_code, "msg": err_msg, "raw": None, "usage": {}}

    try:
        result = resp.json()
    except Exception:
        return {"code": 500, "msg": "Invalid JSON from Gemini", "raw": None, "usage": {}}

    # Extract token usage from Vertex AI usageMetadata
    usage_meta = result.get("usageMetadata", {})
    usage = {
        "prompt_tokens":     usage_meta.get("promptTokenCount"),
        "completion_tokens": usage_meta.get("candidatesTokenCount"),
        "thinking_tokens":   usage_meta.get("thoughtsTokenCount"),
        "total_tokens":      usage_meta.get("totalTokenCount"),
    }
    logger.info(
        "Gemini tokens — prompt:%s completion:%s thinking:%s total:%s",
        usage["prompt_tokens"], usage["completion_tokens"],
        usage["thinking_tokens"], usage["total_tokens"],
    )

    # Gemini 2.5 Flash is a thinking model — skip thought parts
    raw = None
    for part in reversed(result.get("candidates", [{}])[0].get("content", {}).get("parts", [])):
        if "text" in part and not part.get("thought"):
            raw = part["text"]
            break

    if not raw:
        return {"code": 500, "msg": "Gemini returned no content", "raw": None, "usage": usage}

    return {"code": 0, "msg": "success", "raw": raw, "usage": usage}


def _build_animation_prompt(params: dict) -> str:
    category_key       = params.get("market_category", "general")
    category           = CATEGORY_MAP.get(category_key, "General Advertising")
    style              = params.get("ad_style", "Energetic & Dynamic")
    duration           = int(params.get("duration", 5))
    bgm                = BGM_MAP.get(params.get("bgm", "cinematic"), BGM_MAP["cinematic"])
    voice_key          = params.get("voice", "warm_female")
    voice_desc         = VOICE_MAP.get(voice_key, VOICE_MAP["warm_female"])
    has_avatar         = int(params.get("has_avatar", 0))
    has_video_template = int(params.get("has_video_template", 0))
    template_name      = str(params.get("template_name", "")).strip()

    arch_key       = ARCHETYPE_KEY_MAP.get(category_key, category_key)
    arch           = ARCHETYPE_MAP.get(arch_key, ARCHETYPE_MAP["general"])
    dialogue_style = DIALOGUE_STYLE_MAP.get(arch_key, DIALOGUE_STYLE_MAP["general"])
    style_hook     = HOOK_MAP.get(style)
    is_avatar_speaks = style in _AVATAR_SPEAKS_STYLES and (voice_desc is not None)
    is_ugc           = style in _UGC_STYLES

    archetype_block = "\n".join([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"AD ARCHETYPE FOR THIS CATEGORY: {arch['archetype']}",
        "",
        "ADVERTISING PSYCHOLOGY — why buyers in this category purchase:",
        arch["psychology"],
        "",
        "OPENING HOOK (first 2-3 seconds):",
        arch["hook"],
        "",
        "STORY ARC to follow:",
        arch["story_arc"],
        "",
        "KEY VISUAL TECHNIQUES for this category:",
        arch["visuals"],
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ])

    dialogue_target = max(10, round(duration * 2.5))
    dialogue_range  = f"{dialogue_target - 5}–{dialogue_target + 5}"

    style_bg_hint       = STYLE_BG_MAP.get(style)
    category_bg_detail  = CATEGORY_BG_DETAIL_MAP.get(category_key)

    if duration <= 4:
        ts_hook_label = "[0-2s]"
        ts_shot_hint  = "2 shots maximum — this is a very short clip"
        ts_examples   = f"[0-2s]: ...  [2-{duration}s]: ..."
    elif duration <= 7:
        ts_mid        = round(duration * 0.5)
        ts_hook_label = "[0-2s]"
        ts_shot_hint  = "3 shots"
        ts_examples   = f"[0-2s]: ...  [2-{ts_mid}s]: ...  [{ts_mid}-{duration}s]: ..."
    elif duration <= 11:
        ts_mid        = round(duration * 0.55)
        ts_hook_label = "[0-3s]"
        ts_shot_hint  = "3 shots"
        ts_examples   = f"[0-3s]: ...  [3-{ts_mid}s]: ...  [{ts_mid}-{duration}s]: ..."
    else:
        ts_hook_label = "[0-3s]"
        ts_shot_hint  = "4 shots"
        ts_examples   = f"[0-3s]: ...  [3-7s]: ...  [7-11s]: ...  [11-{duration}s]: ..."

    style_costume_note = (
        " CRITICAL FOR UGC AUTHENTICITY: describe the outfit using plain, casual everyday language only — "
        "no \"elegant\", \"sophisticated\", \"chic\", or \"stylish\" adjectives. Even if @Image1 looks slightly "
        "dressed up in the photo, frame it as everyday casual wear (e.g. \"casual top\", \"simple t-shirt\", "
        "\"everyday jeans\"). A real UGC creator looks like a normal person, not a model on a shoot."
    ) if is_ugc else ""

    ugc_tone_override = ""
    if is_ugc:
        ugc_tone_override = "\n".join([
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"UGC AUTHENTICITY OVERRIDE — THIS OVERRIDES THE CATEGORY ARCHETYPE'S VISUAL LANGUAGE:",
            f"The ad style is '{style}'. This means the video must feel like a real person talking to camera on their phone — NOT a polished commercial.",
            "",
            "ATMOSPHERE & TONE: write [Video Pace & Atmosphere] as natural, conversational, and real.",
            "  • DO NOT use: 'sensual', 'cinematic', 'allure', 'luxury', 'refined', 'serene pleasure', 'intimate', 'aspirational', 'atmospheric', 'elegant'",
            "  • DO use: 'natural', 'authentic', 'conversational', 'relaxed', 'genuine', 'real', 'casual', 'direct', 'honest'",
            "",
            "SHOT DIRECTION LANGUAGE: describe @Image1's actions and expressions the way you would direct a real person on a phone, not a model on a luxury shoot.",
            "  • NOT: 'radiating allure', 'a look of serene pleasure', 'exuding confidence', 'sensual gaze'",
            "  • YES: 'laughs naturally', 'smiles at camera', 'reacts genuinely', 'looks excited', 'holds it up to show the camera'",
            "",
            "MUSIC: for UGC style, music should feel casual and background — soft lo-fi, gentle pop, or light acoustic. Avoid 'luxury piano', 'cinematic orchestral', 'refined melody'.",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ])

    # ── AVATAR PATH ──────────────────────────────────────────────────────────
    if has_avatar >= 1:
        product_bases = [v for v in [
            params.get("product_image_base64",   ""),
            params.get("product_image_base64_2", ""),
            params.get("product_image_base64_3", ""),
            params.get("product_image_base64_4", ""),
        ] if v]
        product_count = len(product_bases)
        extra_slot    = 2 + product_count
        has_extra     = bool(params.get("logo_image_base64", ""))
        tpl_hint      = f" (filename: {template_name})" if (has_video_template and template_name) else ""

        img_ref_parts = ["@Image1 = avatar/model"]
        for i in range(product_count):
            slot = i + 2
            img_ref_parts.append(f"@Image{slot} = product " + (str(i + 1) if product_count > 1 else ""))
        if has_extra:
            img_ref_parts.append(f"@Image{extra_slot} = supplementary image")
        has_video_frame = bool(params.get("video_template_frame_base64", ""))
        if has_video_template:
            img_ref_parts.append(
                f"@Video1 = background video{tpl_hint} (still frame attached as LAST image)"
                if has_video_frame
                else f"@Video1 = background video{tpl_hint}"
            )

        if product_count == 1:
            product_analysis_lines = [
                "For @Image2 (product), identify:",
                "  • Exact product type (e.g. body butter, wireless earbuds, leather jacket, ring)",
                "  • Colour, material, size, and form factor",
                "  • Use case: who uses it, when, and exactly how",
                "  • Price tier from visual cues: budget / mid-range / premium / luxury",
            ]
        else:
            product_analysis_lines = ["For each product image, identify: exact product type, colour/material, use case, and price tier."]
            for i in range(product_count):
                slot = i + 2
                product_analysis_lines.append(
                    f"  @Image{slot} (product {i + 1}): [describe it individually — how does it relate to or complement the others?]"
                )
            product_analysis_lines.append("  → Note whether the products are variants of the same item, a bundle, or a collection.")

        product_token_rules = ["  • @Image1 inline wherever the avatar appears in frame"]
        for i in range(product_count):
            slot = i + 2
            label = f" (product {i + 1})" if product_count > 1 else ""
            product_token_rules.append(f"  • @Image{slot}{label} inline wherever that product appears in frame")

        bg_rule = (
            f"  • @Video1 = background scene — avatar/product tokens are composited OVER it, never replacing it"
            if has_video_template
            else (
                "  • No background video provided — you MUST design the setting yourself."
                + (f" ENVIRONMENT RULE FOR AD STYLE '{style}': {style_bg_hint}" if style_bg_hint else " Use the KEY VISUAL TECHNIQUES from Step 2's archetype.")
                + (f" MOST LOGICAL LOCATION FOR {category}: {category_bg_detail}. Use this specific location — it is where a real person would actually encounter this product." if category_bg_detail else "")
                + " Describe the exact location, lighting, and colour palette explicitly in [Video Style & Genre] and [Video Content]. This is NOT optional — every shot needs a described environment."
            )
        )

        lines = (
            [
                "You are a world-class ad director AND TopView Omni Reference prompt engineer.",
                "Follow these 4 steps in order. Think through each one before moving to the next.",
                "Images attached: " + "  |  ".join(img_ref_parts),
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "STEP 1 — ANALYZE EVERY IMAGE",
                "Look at each attached image carefully before writing anything.",
                "",
                "For @Image1 (avatar), identify:",
                "  • Gender  |  Approximate age range (teen / 20s / 30s / 40s+)",
                "  • Apparent ethnicity / nationality — be specific:",
                "    Korean / Japanese / Chinese / Southeast Asian / South Asian / Middle Eastern / Black / White / Hispanic / etc.",
                "  • Skin tone, hair colour and style, facial expression",
                "  • Personal style: casual, professional, athletic, elegant, edgy, bohemian",
                "  • Energy they project: vibrant, calm, authoritative, playful, sensual",
                "",
            ]
            + product_analysis_lines
            + [
                "",
                (f"For @Image{extra_slot} (supplementary): identify what it is and whether it adds value to the ad narrative." if has_extra else ""),
                (
                    (
                        "For @Video1 (background scene) — the LAST attached image is a still frame extracted from this video. Analyze it carefully: setting (beach / gym / city / forest / indoor studio / etc.), time of day, colour palette, lighting mood, energy. The generated prompt must be written to place the avatar and products WITHIN this exact environment."
                        if has_video_frame
                        else "For @Video1 (background): describe the setting (indoor/outdoor), mood, colour palette, lighting."
                    )
                    if has_video_template else ""
                ),
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "STEP 2 — CHOOSE THE AD ARCHETYPE",
                f"Category: {category}  |  Ad style: {style}",
                "",
                archetype_block,
                ugc_tone_override,
                "Based on what you identified in Step 1, select the specific approach within this archetype that fits THIS product best.",
                "If multiple products were uploaded, consider how they can be shown together or sequentially in the ad.",
                "If the archetype has two paths (e.g. sensory vs. expert), choose the one that matches the product type and price tier.",
                "CREATIVE LICENCE: If the product does not obviously belong in this category, do NOT default to generic.",
                "Instead, use the category's ad PSYCHOLOGY and VISUAL STYLE as a creative lens applied to the actual product.",
                "Example: Fragrance category + sports shoes → apply fragrance-style identity cinematography to the shoe (moody, aspirational, cinematic signature).",
                "Example: Baby & Kids category + car seat → lead with the parent-child safety emotion, not product specs.",
                "The unexpected category/product pairing is the creative constraint — lean into it.",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "STEP 3 — DEFINE THE VOICE CHARACTER",
                "Dialogue is ALWAYS in English — TopView TTS only supports English.",
                (
                    f"User's voice preference: {voice_desc}"
                    if voice_desc is not None
                    else "User's voice preference: NONE — no TTS voice selected. Do NOT write any dialogue text. Set voice_character to 'none'. The video will have music only — no spoken words."
                ),
                "",
                "First, assess whether the user's voice choice logically fits @Image1 (gender match AND energy alignment).",
                "Then follow the correct path:",
                "",
                "━━ PATH A — AVATAR SPEAKS (default for all same-gender voices) ━━",
                "→ Use when: the voice gender matches the avatar's gender. This is the DEFAULT path.",
                "→ Same-gender voice = ALWAYS Path A. Do NOT switch to narrator just because the tone is calm, mature, elegant, or formal — those are delivery qualities, not narrator indicators.",
                "→ The voice IS the avatar's own speaking voice.",
                "→ Refine it through these three layers:",
                "",
                "  LAYER 1 — GENDER: female avatar → female voice  |  male avatar → male voice.",
                "",
                "  LAYER 2 — PERSONALITY: match the avatar's energy from Step 1:",
                "    • Athletic / sporty → energetic, driven, direct",
                "    • Polished / elegant → refined, soft, intimate",
                "    • Casual / relaxed → warm, natural, conversational",
                "    • Professional / authoritative → clear, confident, measured",
                "    • Playful / youthful → light, upbeat, enthusiastic",
                "",
                "  LAYER 3 — ETHNICITY: pull @Image1's ethnicity from Step 1, add the cultural delivery character:",
                "    • East Asian (Korean / Japanese / Chinese) → soft, precise, melodic; controlled and expressive",
                "    • Southeast Asian → warm, gentle, friendly cadence",
                "    • South Asian → warm, expressive, slightly lilting rhythm with emotional depth",
                "    • Middle Eastern → rich, warm, elegant tone with confident pacing",
                "    • Black / African → rich, expressive, rhythmic delivery with natural charisma",
                "    • Hispanic / Latina → warm, emotive, energetic with natural warmth",
                "    • White / Western → shaped by personality layer only",
                "",
                "→ Combine all three layers into one specific voice_character.",
                "→ Example: 'warm soft Korean female voice, melodic and precise'  |  'rich expressive Black female voice, rhythmic and natural'",
                "",
                "━━ PATH B — NARRATOR VOICEOVER (only for explicit gender mismatch) ━━",
                "→ Use ONLY when: the voice gender is the opposite of the avatar's gender (e.g. male voice for female avatar, or vice versa).",
                "→ DO NOT use Path B just because the tone sounds elegant, sophisticated, or formal — those are Path A delivery qualities.",
                "→ Honor the user's choice creatively: assign it as an OFF-SCREEN NARRATOR while @Image1 acts and performs.",
                "→ Example: female avatar + deep male voice → male narrator voice describes her actions cinematically while she performs.",
                "→ In voice_character, clearly note how it is used:",
                "   'deep authoritative male narrator voice — off-screen narrator over female avatar acting'",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "STEP 4 — WRITE THE TOPVIEW PROMPT",
                "Using your analysis from Steps 1–3, write the video ad prompt.",
                "ALL 6 sections are required — use EXACTLY these labels:",
                "[Duration]:  [Camera]:  [Video Style & Genre]:  [Video Content]:  [Video Pace & Atmosphere]:  dialogue:",
                "IMPORTANT: the last section is 'dialogue:' — lowercase, no brackets. This is how TopView identifies the character's spoken line.",
                "",
                "Token rules:",
            ]
            + product_token_rules
            + [
                bg_rule,
                (f"  • Use @Image{extra_slot} if it adds genuine value to the ad narrative" if has_extra else ""),
                "Content rules:",
                "  • Follow the opening hook and story arc from Step 2's archetype",
                (f"  • {ts_hook_label} GOLDEN HOOK — Ad Style '{style}' overrides the archetype opening: {style_hook}" if style_hook else ""),
                f"  • BGM — MANDATORY. User's BGM choice: {bgm}",
                "    As ad music director: BGM is required in every video — never omit it.",
                "    VOLUME RULE: regardless of genre, the BGM must always be mixed at FULL, PROMINENT volume — clearly and unmistakably heard on any phone speaker or headphones. Never describe music as soft, quiet, subtle, low, barely audible, or background-only.",
                "    Always respect the user's BGM choice as the foundation. If it fits naturally, use it and refine it to match this ad's exact energy.",
                "    If it does NOT obviously fit the category or ad style, do NOT replace or ignore it — fuse it creatively using one of these techniques:",
                "      • Tempo adapt — keep the user's genre, shift BPM to match the ad pace",
                "        (e.g. upbeat electronic slowed to 75bpm with warm reverb = unexpected luxury feel)",
                "      • Genre blend — layer elements of what naturally fits the category OVER the user's base choice",
                "        (e.g. user chose cinematic orchestral for a sports ad → add driving percussion and staccato brass on top)",
                "      • Category fusion — identify what music naturally fits this specific product category, then fuse it with the user's choice",
                "        (e.g. user chose luxury piano for a baby product → soften with lullaby tempo and gentle bells = warm and sophisticated)",
                "        (e.g. user chose upbeat pop for a skincare ad → strip to airy vocals and soft synth pads = fresh and youthful)",
                "      • Emotional bridge — find the shared emotional register between the user's choice and the category's natural sound",
                "        (e.g. user chose cinematic for a casual fashion ad → keep the build structure, replace strings with indie guitar swell)",
                "    → Write a specific, vivid music description that preserves the sonic energy and presence level of the user's BGM choice.",
                "    → 'No background music' = always honored exactly, never add music.",
                "  • BGM LINE: immediately after the Voice Spec line, add on its own line inside [Video Content]:",
                "    'Background Music: [your vivid music description]'",
                "    Do NOT write a separate top-level [Video Music] section outside [Video Content]. TopView only reads labels inside [Video Content].",
                f"  • SPEAKING RULE — determined by the Ad Style selected by the user: '{style}'",
                "    AVATAR SPEAKS — person IS the message, dialogue comes from @Image1's mouth:",
                "      'UGC – Talking Head', 'UGC – Funny & Relatable', 'Get Ready With Me (GRWM)', 'Before & After',",
                "      'Tutorial / How-To', 'Unboxing & First Reaction', 'Expert / Specialist Endorsement',",
                "      'Problem → Solution', 'Emotional Storytelling', 'Flash Offer / Direct Response', 'Product Hero Showcase'",
                "      → MANDATORY VISUAL REQUIREMENT: at least ONE dedicated timestamp must show @Image1 in a CLOSE-UP facing the camera directly — animated facial expressions, mouth clearly forming words, natural hand gestures, maintaining direct eye contact. This shot must contain the exact phrase 'speaking to the viewer' or 'speaking to the camera'.",
                "      → This close-up speaking shot must be SELF-CONTAINED — do NOT combine it with other actions like 'walks in and picks up the product while speaking.' A single shot cannot do three things at once. The speaking timestamp must be ONLY about @Image1 facing camera and talking.",
                "      → EXAMPLE of a CORRECT speaking timestamp: '[4-8s]: @Image1 in medium close-up, face fully toward camera, animated and expressive — mouth forming words naturally, making direct eye contact with the viewer, one hand gesturing lightly, speaking to the viewer about how this product changed her routine.'",
                "      → EXAMPLE of an INCORRECT speaking timestamp: '[4-8s]: @Image1 enters frame, picks up @Image2, turns to camera, speaking to the viewer.' (Too many actions — the video model ignores the speaking and shows the actions instead.)",
                "      → Do NOT use synonyms like 'talking', 'addressing', 'facing camera' — ONLY 'speaking to the viewer' or 'speaking to the camera' in this timestamp.",
                "    NARRATOR VOICEOVER — product IS the star, @Image1 acts/performs, dialogue plays over the action:",
                "      'Luxury Product Reveal', 'Performance / In-Action', 'Lifestyle Aesthetic'",
                "      → @Image1 moves, demonstrates, or appears in scene — but does NOT face camera and speak.",
                "      → Do NOT write '@Image1 speaking to camera' for these styles.",
                "    MIXED — cinematic reveal with one personal testimony moment:",
                "      'K-Beauty / Skincare Ritual'",
                "      → Open with product close-up (narrator), then one dedicated shot of @Image1 in close-up facing camera and speaking (apply the AVATAR SPEAKS close-up rule above for that shot).",
                "  • CONSTRAINTS LINE: the very first line of [Video Content] must be: 'Constraints: Strictly follow all asset references. Do not substitute or add visual elements not described.'",
                f"  • AVATAR OUTFIT LOCK: if the ad concept explicitly calls for a specific outfit (e.g. 'silk blouse', 'athletic wear'), use that description and add 'Same outfit throughout entire video.' If no outfit is specified, look at what @Image1 is actually wearing in Step 1 and describe that instead — then add 'Same outfit throughout entire video.' Never invent a new outfit and never allow mid-video clothing changes.{style_costume_note}",
                "  • VOICE SPEC LINE: after the Constraints line, add: 'Voice Spec: [voice_character from Step 3]' — embed it directly in [Video Content] so TopView reads it. Then on the NEXT line add the Background Music line (see BGM rule above). Both lines must be inside [Video Content], before the first timestamp.",
                "  • NO WARDROBE CHANGES: never write a story arc that requires @Image1 to change clothes mid-video. One consistent look throughout.",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "⚠️  MANDATORY INTERACTION RULE — NON-NEGOTIABLE",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "@Image1 (avatar) MUST physically interact with EVERY product in at least one timestamp.",
                "Interaction means one of: holding it, picking it up, applying it to skin/hair/body, wearing it, spraying it, drinking/eating it, demonstrating it in use, or presenting it directly toward the camera.",
                "These are NOT acceptable as the only product appearance:",
                "  ✗ Product sitting on a surface while avatar stands nearby",
                "  ✗ Product visible in the background or on a shelf",
                "  ✗ Avatar gesturing toward the product without touching it",
                "  ✗ Product shown in a solo close-up shot with no avatar contact",
                "Every product token uploaded MUST appear at least once AND be actively in the avatar's hands or on their body.",
                "Spread interactions naturally across timestamps — do NOT cluster all products into one single shot.",
                "TopView will reject the task if any uploaded image token is missing from [Video Content].",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "⚠️  MANDATORY BANNER FRAME RULE — NON-NEGOTIABLE",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "Every video MUST contain at least one timestamp where @Image1's face AND the product are SIMULTANEOUSLY visible in the SAME frame:",
                "  ✓ @Image1's face fully toward the camera",
                "  ✓ The product fully within the frame — not cropped at any edge, not obscured, not blurred",
                "  ✓ The moment is relatively still — NOT mid-flip, mid-pour, mid-swing, or during rapid action",
                "This is the frame extracted as the ad thumbnail and Instagram banner. If it does not exist, the banner will show only the product with no person.",
                "",
                "CRITICAL SIZE RULE — the product must be LARGE in the frame, not tiny:",
                "  The product must be held CLOSE to the camera — at chin/chest level, filling at least 20% of the frame width.",
                "  'Beside her face at arm's length' is NOT enough — at that distance a small product (lipstick, bottle, supplement) becomes a tiny sliver and is invisible in a thumbnail.",
                "  The product should feel large and unmissable — like a product photo shot up-close, not a lifestyle prop in the background.",
                "",
                "How to satisfy this rule for each ad style:",
                "  Action-heavy styles (cooking, sports, fitness, cleaning, unboxing, performance):",
                "    → Add a dedicated 1–2 second pause: @Image1 lifts @Image2 CLOSE toward the camera at chin/chest level — product filling the lower half of the frame, face in the upper half.",
                "    → WRONG: '@Image1 holds @Image2 up toward camera' (vague — product may be small and far)",
                "    → RIGHT: '@Image1 brings @Image2 up close to the camera at chest level, product large and prominent in the lower frame, face clearly visible above it — both sharp and still.'",
                "  Speaking styles (UGC, tutorial, talking head, expert, product showcase):",
                "    → The speaking-to-viewer timestamp MUST have @Image2 held CLOSE to the camera at chin or chest level — product large and unmissable, not a tiny object held at arm's length to the side.",
                "    → WRONG: '[7-11s]: @Image1 holds @Image2 clearly beside her face, speaking to viewer.' (beside = arm's length = product too small in frame)",
                "    → RIGHT: '[7-11s]: @Image1 faces camera, brings @Image2 up close at chin level — product large and prominent in the lower portion of the frame, face visible in the upper portion, speaking to viewer — both sharp and still.'",
                "  Small products (lipstick, serum, supplement bottle, small jewellery):",
                "    → These MUST be held very close to the camera — at chin level, filling the bottom quarter of the frame.",
                "    → Do NOT describe them as 'held beside the face' or 'held at shoulder level' — they will be invisible in a thumbnail at that distance.",
                "  Lifestyle / emotional / fragrance / luxury styles:",
                "    → At least one shot must show @Image1 with the product held close at chin/chest level, face visible, product large in frame.",
                "  Before & After / GRWM / skincare ritual:",
                "    → The reveal or application moment must show both face and product large in the same still frame.",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"  • TIMESTAMPS: structure [Video Content] with exactly {ts_shot_hint} using explicit time cuts. HARD LIMIT: all timestamps must fit within 0–{duration}s — never write a timestamp that exceeds {duration}s. Example pattern for a {duration}s video: '{ts_examples}'. Vague transitions ('then', 'next', 'quick cut to') cause the AI to merge shots unpredictably.",
                "  • dialogue: write ONLY the spoken words — no quotes, no character prefix, no asterisks, no '@Image1:' prefix. Just the raw speech text.",
                f"  • dialogue LENGTH: {dialogue_range} words total. At a natural conversational pace this fills {duration} seconds exactly.",
                "  • dialogue MUST BE A COMPLETE, WRAPPED THOUGHT — it cannot feel cut off mid-sentence at the end. Structure it as: hook opening (1 punchy line) → product benefit (1–2 sentences) → clear call-to-action close (1 short line). The very last word must be a natural ending, not a trailing comma, conjunction, or incomplete idea.",
                "  • dialogue: DO NOT end with '...' or any ellipsis — ellipsis signals an unfinished thought. End with a complete sentence.",
                f"  • dialogue point-of-view: {dialogue_style['pov']}",
                f"  • dialogue style: {dialogue_style['style']}",
                f"  • dialogue example tone — do NOT copy verbatim: {dialogue_style['example']}",
                "  • dialogue: NEVER write narrator lines like 'Pure elegance.' / 'Elevate your game.' — those are announcer copy, not the avatar speaking.",
                (
                    f"  • dialogue AVATAR SPEAKS CHECK: The ad style '{style}' requires the avatar to be talking directly to the viewer. The dialogue MUST sound like a real person speaking on camera — personal, direct, first-person. NOT polished announcer copy. WRONG: 'Sometimes, all it takes is one perfect piece to transform your entire outlook.' (narrator cadence — poetic opener, no 'I'). RIGHT: 'Okay I was not expecting to fall this hard for this bag — but here I am and I wear it every single day.' (personal, direct, first-person). Start with 'I', 'Okay', 'So', 'Honestly', 'This', or a direct personal statement — NOT a poetic abstract phrase."
                    if is_avatar_speaks else ""
                ),
                f"  • Duration: {duration} seconds  |  No markdown outside labels",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "Return ONLY this JSON — no extra text outside the JSON:",
                "{",
                '  "avatar_analysis": "<Step 1: gender, age, ethnicity, style, energy of @Image1>",',
                '  "product_analysis": "<Step 1: all products identified — name, tier, use case, relationship between them if multiple>",',
                '  "archetype_used": "<archetype name chosen in Step 2>",',
                '  "detected_language": "English",',
                '  "voice_character": "<specific voice character from Step 3 — e.g. \'soft warm female voice, gentle and intimate\'>",',
                '  "prompt": "<PLAIN TEXT STRING — write each section on its own line using [Label]: value format exactly as shown above. DO NOT nest a JSON object inside this field.>"',
                "}",
            ]
        )
        return "\n".join(lines)

    # ── NO-AVATAR PATH ────────────────────────────────────────────────────────
    if duration <= 6:
        shot_count = "2 shots"
        pace_note  = "Short clip — 2 smooth shots."
    elif duration <= 10:
        shot_count = "3 shots"
        pace_note  = "Medium clip — 3 shots, moderate pacing."
    else:
        shot_count = "4-5 shots"
        pace_note  = "Standard ad — 4-5 shots with a full narrative arc."

    tpl_hint_no_av  = f" (filename: {template_name})" if (has_video_template and template_name) else ""
    has_video_frame = bool(params.get("video_template_frame_base64", ""))

    vid_ref_no_av = (
        (
            f"@Video1 = background video{tpl_hint_no_av} (still frame attached as LAST image)"
            if has_video_frame
            else f"@Video1 = background video{tpl_hint_no_av}"
        )
        if has_video_template else ""
    )

    bg_rule_no_av = (
        "  • @Video1 = background — @Image2 composited OVER it, never replacing it"
        if has_video_template
        else (
            "  • No background video provided — design the scene yourself."
            + (f" ENVIRONMENT RULE FOR AD STYLE '{style}': {style_bg_hint}" if style_bg_hint else " Use the KEY VISUAL TECHNIQUES from Step 2's archetype.")
            + (f" MOST LOGICAL LOCATION FOR {category}: {category_bg_detail}. Use this specific location — it is where a real person would actually encounter this product." if category_bg_detail else "")
            + " Describe the exact setting, lighting, and colour palette in [Video Style & Genre] and [Video Content]."
        )
    )

    lines = [
        "You are a world-class ad director AND TopView Omni Reference prompt engineer.",
        "Follow these 3 steps in order. Think through each one before moving to the next.",
        (
            f"Images attached: @Image2 = the product  |  {vid_ref_no_av}"
            if has_video_template
            else "Image attached: @Image2 = the product."
        ),
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 1 — ANALYZE THE PRODUCT IMAGE",
        "Look at @Image2 carefully before writing anything.",
        "  • Exact product type (e.g. body butter, wireless earbuds, running shoes)",
        "  • Colour, material, size, and form factor",
        "  • Use case: who uses it, when, and how",
        "  • Price tier from visual cues: budget / mid-range / premium / luxury",
        (
            (
                "\nFor @Video1 (background scene) — the LAST attached image is a still frame extracted from this video. Analyze it carefully: setting, time of day, colour palette, lighting mood. The generated prompt must place the product WITHIN this exact environment.\n"
                if has_video_frame
                else "\nFor @Video1 (background): describe the setting, mood, and lighting.\n"
            )
            if has_video_template else ""
        ),
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 2 — CHOOSE THE AD ARCHETYPE",
        f"Category: {category}  |  Ad style: {style}",
        "",
        archetype_block,
        ugc_tone_override,
        "Based on what you identified in Step 1, select the specific approach that fits THIS product best.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "STEP 3 — WRITE THE TOPVIEW PROMPT",
        f"Using Steps 1–2, write a {shot_count} video ad prompt.",
        "ALL 8 sections required — use EXACTLY these labels:",
        "[Duration]:  [Camera]:  [Video Style & Genre]:  [Video Music]:  [Hook (first 3s)]:  [Video Content]:  [Video Pace & Atmosphere]:  dialogue:",
        "IMPORTANT: the last section is 'dialogue:' — lowercase, no brackets.",
        "",
        "  • @Image2 inline wherever the product appears",
        bg_rule_no_av,
        "  • Follow the opening hook and story arc from Step 2's archetype",
        (f"  • {ts_hook_label} GOLDEN HOOK — Ad Style '{style}' overrides the archetype opening: {style_hook}" if style_hook else ""),
        f"  • [Video Music] — user's BGM choice: {bgm}",
        "    As ad music director: assess whether this fits the product's mood and the ad style.",
        "    VOLUME RULE: regardless of genre, the BGM must always be mixed at FULL, PROMINENT volume — clearly and unmistakably heard on any phone speaker or headphones. Never describe music as soft, quiet, subtle, low, barely audible, or background-only.",
        "    → If it FITS: use it, then refine the description to the specific energy, tempo, and emotion of THIS ad.",
        "    → If it does NOT obviously fit: DO NOT replace it. Fuse or adapt it creatively:",
        "      • Tempo adapt — keep the genre, shift BPM to match the ad pace",
        "      • Genre blend — layer elements of what naturally fits OVER the user's base",
        "      • Emotional bridge — find the shared emotional register between the two genres",
        "    → Write a vivid music description that preserves the sonic energy and presence level of the user's BGM choice.",
        "    → 'No background music' = always honored exactly, never add music.",
        "  • dialogue: write ONLY the spoken words — no quotes, no character prefix, no asterisks. Just the raw speech text.",
        f"  • dialogue LENGTH: {dialogue_range} words total. At a natural conversational pace this fills {duration} seconds exactly.",
        "  • dialogue MUST BE A COMPLETE, WRAPPED THOUGHT — it cannot feel cut off mid-sentence at the end. Structure it as: hook opening (1 punchy line) → product benefit (1–2 sentences) → clear call-to-action close (1 short line). The very last word must be a natural ending, not a trailing comma, conjunction, or incomplete idea.",
        "  • dialogue: DO NOT end with '...' or any ellipsis — ellipsis signals an unfinished thought. End with a complete sentence.",
        f"  • dialogue point-of-view: {dialogue_style['pov']}",
        f"  • dialogue style: {dialogue_style['style']}",
        f"  • dialogue example tone — do NOT copy verbatim: {dialogue_style['example']}",
        "  • dialogue: NEVER write announcer lines like 'Pure elegance.' / 'Feel the difference.' — narrator copy.",
        (f"  • dialogue voice character: {voice_desc}" if voice_desc else "  • dialogue: None — on-screen text only."),
        f"  • Duration: {duration}s ({pace_note})  |  No markdown outside labels",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "Return ONLY this JSON — no extra text outside the JSON:",
        "{",
        '  "product_analysis": "<Step 1: exact product, tier, use case>",',
        '  "archetype_used": "<archetype name chosen in Step 2>",',
        '  "prompt": "<PLAIN TEXT STRING — write each section on its own line using [Label]: value format exactly as shown above. DO NOT nest a JSON object inside this field.>"',
        "}",
    ]
    return "\n".join(lines)


def _convert_prompt_tokens(prompt_text) -> str:
    """Convert @ImageN / @VideoN notation to <<<ImageN>>> / <<<VideoN>>> tokens."""
    if isinstance(prompt_text, dict):
        lines = []
        for k, v in prompt_text.items():
            v = " ".join(v) if isinstance(v, list) else str(v)
            lines.append(f"dialogue: {v}" if k.lower().strip() == "dialogue" else f"[{k.strip()}]: {v}")
        prompt_text = "\n".join(lines)
    else:
        prompt_text = str(prompt_text)
        trimmed = prompt_text.strip()
        if trimmed.startswith("{"):
            try:
                decoded = json.loads(trimmed)
                if isinstance(decoded, dict):
                    lines = []
                    for k, v in decoded.items():
                        v = " ".join(v) if isinstance(v, list) else str(v)
                        lines.append(f"dialogue: {v}" if k.lower().strip() == "dialogue" else f"[{k.strip()}]: {v}")
                    prompt_text = "\n".join(lines)
            except Exception:
                pass

    for i in range(1, 7):
        prompt_text = prompt_text.replace(f"@Image{i}", f"<<<Image{i}>>>").replace(f"@Image {i}", f"<<<Image{i}>>>")
    prompt_text = prompt_text.replace("@Video1", "<<<Video1>>>").replace("@Video 1", "<<<Video1>>>")
    return prompt_text


# ── Public API ──────────────────────────────────────────────────────────────

def generate_animation_prompt(params: dict) -> dict:
    prompt = _build_animation_prompt(params)

    images: list[str] = []
    has_avatar = int(params.get("has_avatar", 0))
    if has_avatar >= 1 and params.get("avatar_image_base64"):
        images.append(params["avatar_image_base64"])
    for key in ["product_image_base64", "product_image_base64_2", "product_image_base64_3", "product_image_base64_4"]:
        if params.get(key):
            images.append(params[key])
    if params.get("video_template_frame_base64"):
        images.append(params["video_template_frame_base64"])

    res = _call_gemini(prompt, images)
    if res["code"] != 0:
        return {"code": res["code"], "msg": res["msg"], "prompt": None, "usage": res.get("usage", {})}

    raw = res["raw"]
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        pass
    if not parsed:
        try:
            clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            clean = re.sub(r"```\s*$", "", clean, flags=re.MULTILINE)
            parsed = json.loads(clean.strip())
        except Exception:
            pass
    if not parsed:
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
        except Exception:
            pass

    if not parsed or not parsed.get("prompt"):
        logger.error("Animation prompt raw response: %s", raw[:500] if raw else "empty")
        return {"code": 500, "msg": "Gemini returned invalid JSON", "prompt": None, "usage": res.get("usage", {})}

    prompt_text = _convert_prompt_tokens(parsed["prompt"])

    # Enforce the correct duration
    enforced_duration = int(params.get("duration", 5))
    prompt_text = re.sub(
        r"^\[?[Dd]uration\]?:[^\n]*",
        f"[Duration]: {enforced_duration} seconds",
        prompt_text,
        flags=re.MULTILINE,
    )

    return {
        "code":             0,
        "msg":              "success",
        "prompt":           prompt_text.strip(),
        "avatar_analysis":  parsed.get("avatar_analysis"),
        "product_analysis": parsed.get("product_analysis"),
        "archetype_used":   parsed.get("archetype_used"),
        "detected_language": parsed.get("detected_language"),
        "voice_character":  parsed.get("voice_character"),
        "usage":            res["usage"],
    }


def identify_best_segments(animation_prompt: str, category: str = "") -> dict:
    if not animation_prompt.strip():
        return {"code": 500, "msg": "No prompt provided", "segments": []}

    category_line = f'The ad category is "{category}". This is the PRIMARY product being sold.\n' if category else ""

    prompt = f"""You are a film editor selecting the best time segments from a video ad script for a static banner frame.

A great banner frame needs BOTH: (1) the person's face + body clearly visible, AND (2) the PRIMARY advertised product clearly in frame.

{category_line}
━━ WHAT COUNTS AS THE PRIMARY PRODUCT ━━
The PRIMARY product is the item being SOLD — the one that matches the ad category above.
Props, outfits the model wears during the shoot, and supporting accessories are NOT the primary product, even if they appear in the video.

Examples:
  • Category "Fragrance & Perfume" → the perfume bottle is primary. The elegant dress worn during the shoot is a PROP.
  • Category "Beauty & Cosmetics"  → the lipstick/serum/palette is primary. The dress is a PROP.
  • Category "Fashion & Apparel"   → the dress/jacket/shoes is primary. A perfume spritzed for ambience is a PROP.
  • Category "Jewellery"           → the necklace/ring/earring is primary. The dress is a PROP.
  • Category "Health & Wellness"   → the supplement bottle is primary. The gym outfit is a PROP.

━━ RANKING RULES ━━
RANK HIGH — person AND PRIMARY product both clearly present:
  - Person holds/presents/sprays/applies/interacts with the PRIMARY product
  - Medium close-up showing face + PRIMARY product label or form factor

RANK MEDIUM — person present but PRIMARY product uncertain or transitioning:
  - Person wearing or holding a PROP/outfit (not the primary product)
  - Wide establishing shot where primary product may be in scene but not featured
  - Person performing an action while primary product is in background

RANK LOW — person or PRIMARY product absent:
  - Close-up of the primary product alone (no face)
  - Close-up of a PROP or outfit only
  - Person in extreme motion without primary product contact
  - Text cards, title screens, transitions

VIDEO SCRIPT:
{animation_prompt}

Return a JSON array sorted best-first. Include ALL [Xs-Ys]: segments found in the script:
[
  {{"start": 4.0, "end": 9.0, "priority": "high", "reason": "person holds fragrance bottle close to camera at chin level — face and primary product both visible"}},
  {{"start": 9.0, "end": 15.0, "priority": "high", "reason": "person sprays fragrance, face and profile visible"}},
  {{"start": 1.0, "end": 4.0, "priority": "medium", "reason": "person holds dress (PROP) up to herself — primary product (fragrance) not yet present"}},
  {{"start": 0.0, "end": 1.0, "priority": "low", "reason": "hero shot of dress only, no person"}}
]

Rules:
- start/end must be numbers (seconds) exactly matching the [Xs-Ys] timestamps in the script
- priority: "high" = person + PRIMARY product definitely described | "medium" = person present but primary product absent/uncertain | "low" = one or both absent
- If no [Xs-Ys] timestamps found in the script, return [{{"start": 0.0, "end": 999.0, "priority": "high", "reason": "no timestamps found"}}]
- Return ONLY the JSON array — no extra text"""

    res = _call_gemini(prompt, [])
    if res["code"] != 0:
        return {"code": res["code"], "msg": res["msg"], "segments": [], "usage": res.get("usage", {})}

    raw = res["raw"]
    try:
        parsed = json.loads(raw)
    except Exception:
        clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        clean = re.sub(r"```\s*$", "", clean, flags=re.MULTILINE)
        try:
            parsed = json.loads(clean.strip())
        except Exception:
            return {"code": 500, "msg": "Gemini returned invalid JSON for segments", "segments": []}

    if not isinstance(parsed, list):
        return {"code": 500, "msg": "Gemini returned invalid JSON for segments", "segments": []}

    valid_priorities = {"high", "medium", "low"}
    segments = []
    for seg in parsed:
        if not isinstance(seg, dict) or "start" not in seg or "end" not in seg:
            continue
        segments.append({
            "start":    float(seg["start"]),
            "end":      float(seg["end"]),
            "priority": seg.get("priority", "medium") if seg.get("priority") in valid_priorities else "medium",
            "reason":   seg.get("reason", ""),
        })

    logger.info("identify_best_segments: %d segments found", len(segments))
    return {"code": 0, "msg": "success", "segments": segments, "usage": res["usage"]}


def _build_gemini_banner_prompt(params: dict, img_map: dict) -> str:
    category  = params.get("category", "General Advertising")
    ad_style  = params.get("ad_style", "")
    avatar_ref = f"Image {img_map['avatar']}" if "avatar" in img_map else "the first image"
    prod_refs  = (
        ", ".join(f"Image {i}" for i in img_map["products"])
        if img_map.get("products")
        else "the product image"
    )
    cover_line = (
        f"- Image {img_map['cover']}: Video scene thumbnail — mirror its environment, colour palette, and lighting mood in the background"
        if "cover" in img_map else ""
    )
    return f"""You are a world-class advertising art director and commercial photographer.

Images attached:
- {avatar_ref}: The model/avatar — YOU MUST reproduce this person's exact face, skin tone, and hair faithfully. Do not idealise, smooth, or replace their face with a different one.
- {prod_refs}: The product(s) — study shape, colour, branding, label, and material
{cover_line}

GENERATE a single professional 9:16 vertical banner ad image (portrait, 1080×1920 px ratio).

FACE FIDELITY — CRITICAL:
Reproduce the person from {avatar_ref} with their EXACT facial features. This is the most important requirement. Do not generate a "similar looking" or "idealised" version — reproduce the actual person.

PRODUCT INTERACTION — identify the product type and choose:
• Clothing, dress, top, jacket → avatar WEARING it (fully dressed in it)
• Skincare, serum, cream, makeup → avatar mid-application, product bottle in one hand
• Fragrance → avatar holding bottle at chest/collarbone, eyes closed or gazing away
• Food, beverage → avatar mid-drink or presenting product with genuine delight, label visible
• Electronics → avatar operating it hands-on
• Jewellery, watch → avatar wearing on correct body part
• Shoes, sneakers → avatar wearing them, footwear clearly visible
• Bags, handbags → avatar wearing/carrying as fashion statement
• Sports gear → avatar in active pose using it
• Other → most natural real-use context for this specific product

COMPOSITION:
• 9:16 vertical portrait format
• Subject fills upper 60-70% of frame
• Product clearly visible and identifiable
• Product label/logo facing camera, readable
• Clean breathing room at sides

LIGHTING:
• Large softbox key light 45° from one side
• Reflector or fill light from opposite side
• Rim/hair light from behind for subject separation
• Natural catchlights visible in eyes

PHOTOGRAPHY STYLE:
• Professional commercial photography, magazine quality
• Shallow depth of field — subject sharp, background softly blurred
• Skin texture natural and realistic — not airbrushed or over-smoothed
• Category: {category} | Ad style: {ad_style}

BACKGROUND:
• Match the setting and colour temperature from the video scene thumbnail
• Same environment type (indoor studio / outdoor / lifestyle setting)
• Background clearly separated from subject

ABSOLUTE RESTRICTIONS:
• No text, no watermarks, no overlays
• No additional people
• No distorted or extra fingers/hands
• Photorealistic only

Generate the image."""


def generate_banner_with_gemini(params: dict) -> dict:
    try:
        access_token = _get_access_token()
    except Exception as exc:
        return {"code": 500, "msg": str(exc), "base64": None, "mime": None}

    url = (
        f"https://{_LOCATION}-aiplatform.googleapis.com/v1/projects/{_PROJECT_ID}"
        f"/locations/{_LOCATION}/publishers/google/models/{_MODEL}:generateContent"
    )

    parts: list[dict] = []
    img_idx = 1
    img_map: dict = {}

    if params.get("avatar_image_base64"):
        b64 = params["avatar_image_base64"]
        mime = "image/jpeg"
        m = re.match(r"^data:(image/\w+);base64,(.+)$", b64, re.DOTALL)
        if m:
            mime, b64 = m.group(1), m.group(2)
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        img_map["avatar"] = img_idx
        img_idx += 1

    prod_idxs = []
    for key in ["product_image_base64", "product_image_base64_2", "product_image_base64_3", "product_image_base64_4"]:
        if params.get(key):
            b64 = params[key]
            mime = "image/jpeg"
            m = re.match(r"^data:(image/\w+);base64,(.+)$", b64, re.DOTALL)
            if m:
                mime, b64 = m.group(1), m.group(2)
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})
            prod_idxs.append(img_idx)
            img_idx += 1
    img_map["products"] = prod_idxs

    if params.get("cover_image_base64"):
        b64 = params["cover_image_base64"]
        mime = "image/jpeg"
        m = re.match(r"^data:(image/\w+);base64,(.+)$", b64, re.DOTALL)
        if m:
            mime, b64 = m.group(1), m.group(2)
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})
        img_map["cover"] = img_idx
        img_idx += 1

    parts.append({"text": _build_gemini_banner_prompt(params, img_map)})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "temperature": 1.0},
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            timeout=180,
            verify=False,
        )
    except requests.RequestException as exc:
        return {"code": 500, "msg": f"Connection error: {exc}", "base64": None, "mime": None}

    if resp.status_code != 200:
        try:
            err = resp.json().get("error", {}).get("message", f"Gemini image gen error (HTTP {resp.status_code})")
        except Exception:
            err = f"Gemini image gen error (HTTP {resp.status_code})"
        return {"code": resp.status_code, "msg": err, "base64": None, "mime": None}

    try:
        result = resp.json()
    except Exception:
        return {"code": 500, "msg": "Invalid JSON from Gemini", "base64": None, "mime": None}

    for part in (result.get("candidates", [{}])[0].get("content", {}).get("parts", [])):
        if part.get("inline_data", {}).get("data"):
            return {
                "code":   0,
                "msg":    "success",
                "base64": part["inline_data"]["data"],
                "mime":   part["inline_data"].get("mime_type", "image/png"),
            }

    return {"code": 500, "msg": "Gemini returned no image data", "base64": None, "mime": None}


def build_banner_imagen_prompt(params: dict) -> dict:
    contact_sheet       = params.get("contact_sheet", "")
    frame_count         = int(params.get("frame_count", 0))
    category            = params.get("category", "General Advertising")
    ad_style            = params.get("ad_style", "")
    has_logo            = bool(params.get("has_logo", False))
    is_product_fallback = bool(params.get("is_product_fallback", False))

    if not contact_sheet or frame_count == 0:
        return {"code": 500, "msg": "No contact sheet provided", "imagen_prompt": None, "best_frame_index": 0}

    if is_product_fallback:
        return _build_banner_prompt_product_fallback(params, contact_sheet, frame_count, category, ad_style, has_logo)

    logo_rule = (
        'LOGO LOCKUP (replace SENTENCE 3 entirely with this): The second input image is the brand logo. Create a horizontal brand lockup at the very bottom of the frame — logo on the LEFT, tagline text on the RIGHT, both vertically centred on the same baseline. The logo height must match the tagline text cap-height exactly. Write: "Place the brand logo (from the second input image) to the left of the tagline text, same height as the text cap-height, horizontally aligned — together forming a single brand lockup centred at the very bottom of the frame, clear of the person and product." Do NOT place the logo separately from the tagline text.'
        if has_logo else ""
    )

    prompt = f"""You are a world-class advertising creative director reviewing a contact sheet of {frame_count} video frames from a {category} product ad in "{ad_style}" style. Each frame thumbnail has its NUMBER printed in the top-left corner.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 1 — PICK THE BEST FRAME
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Scan every numbered cell on the contact sheet. For EACH cell, answer THREE binary questions before doing anything else:

  Q1 — Is a human person (face + body) unmistakably visible in this frame?  YES / NO
  Q2 — Is the product clearly recognisable in this frame?                    YES / NO
  Q3 — Is the product fully within the frame boundaries (not cropped at edges)?  YES / NO

━━ DISQUALIFICATION RULES (apply before any scoring) ━━
  If Q1 = NO  → frame is DISQUALIFIED. Skip it.
  If Q2 = NO  → frame is DISQUALIFIED. Skip it.
  If Q3 = NO  → frame is DISQUALIFIED.
  Product-only shots, close-ups of the product alone with no person, title cards, transition frames → all DISQUALIFIED.
  Extreme close-up: if the product or person fills more than 75% of the frame with no visible background → DISQUALIFIED.
  There is no "closest match" exception. A disqualified frame is never chosen over a qualified one.

━━ SCORING (applies only to frames where Q1 = YES AND Q2 = YES AND Q3 = YES) ━━
Score each qualified frame on these 7 criteria — one point each:
  1. SHARPNESS — face and body in sharp focus
  2. EXPRESSION — genuine and emotionally appropriate
  3. GAZE — natural and intentional for the mood
  4. LIGHTING — face and product well-lit
  5. COMPOSITION — strong visual balance
  6. PRODUCT PRESENCE — clearly visible and well-positioned
  7. TEXT SPACE — at least one clean zone for a headline/tagline

Score each qualified frame 0–7. Pick the frame with the HIGHEST score.
Return its cell number as "best_frame_number".

━━ AFTER PICKING — set these fields honestly ━━
  "person_visible"  — true if the winning frame has a clearly visible human person
  "product_visible" — true if the winning frame has a clearly visible product

Quality of the winning frame:
  "excellent"  — score 6–7 out of 7
  "good"       — score 4–5 out of 7
  "none"       — every frame fails the disqualifiers, OR every qualified frame scores 0–3

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — TEXT CONTENT & PLACEMENT DECISIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A) HEADLINE (2–3 words, ALL CAPS) — emotional transformation this product delivers
B) BRAND NAME — read from the product packaging in the selected frame. If unreadable, write "".
C) TAGLINE — "[Brand Name] — [2–3 word benefit]". Total 4–7 words.
D) PLACEMENT — where is pure empty background visible?
   Default "top_bottom" for most portrait shots.
   "side_left" or "side_right" only if person occupies < 40% of frame width on that side.
   "tight_crop" if face/body fills 80%+ of frame height.
E) COLOUR — derive from the product packaging dominant accent colour; do NOT default to white automatically.
F) DROP SHADOW — true if text zone is light or mid-tone, false if consistently dark.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — WRITE THE GPT IMAGE 2 EDIT PROMPT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITICAL CONSTRAINT:
GPT Image 2 is an image EDITOR. DO NOT ask it to change the person's face, gaze, expression, outfit, hair, pose, or hand positions.
The ONLY job of this prompt is to ADD TEXT overlays onto the existing photograph.

Write a GPT Image 2 prompt in EXACTLY this 4-sentence structure. Total length: 50–80 words.

SENTENCE 1 — HARD PRESERVE (always first, non-negotiable):
"This is a photo editing task only — do not alter the person's face, skin tone, hair, clothing, outfit, body shape, pose, hand positions, expression, or the background in any way; the photograph must remain pixel-for-pixel identical except for the text additions below."

SENTENCE 2 — HEADLINE: Add "[HEADLINE]" in the appropriate font, material treatment, palette-derived colour, and position, casting a shadow aligned with the scene's dominant light direction to anchor the text physically in the image.
SENTENCE 3 — TAGLINE: Add "[TAGLINE]" in the same font at lighter weight, same material treatment at half-opacity, same colour, at the appropriate position.
SENTENCE 4 — NEGATIVE CONSTRAINTS: "No other text, no watermarks, no invented logos, no alterations to the background, lighting, person, clothing, or any other part of the photograph."

{logo_rule}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY valid JSON — no markdown, no explanation:
{{
  "best_frame_number": 7,
  "best_frame_score": 6,
  "person_visible": true,
  "product_visible": true,
  "quality": "excellent",
  "frame_pick_reason": "...",
  "imagen_prompt": "...",
  "text_specs": {{
    "headline": "BOLD COLOUR",
    "tagline": "Saint Laurent — Own The Room",
    "brand_name": "Saint Laurent",
    "headline_color": "#FFFFFF",
    "tagline_color": "#FFFFFF",
    "placement": "top_bottom",
    "drop_shadow": true
  }}
}}"""

    res = _call_gemini(prompt, [contact_sheet])
    if res["code"] != 0:
        return {"code": res["code"], "msg": res["msg"], "imagen_prompt": None, "best_frame_index": 0, "usage": res.get("usage", {})}

    raw = res["raw"]
    parsed = None
    # Attempt 1: direct parse
    try:
        parsed = json.loads(raw)
    except Exception:
        pass
    # Attempt 2: strip markdown fences
    if not parsed:
        try:
            clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            clean = re.sub(r"```\s*$", "", clean, flags=re.MULTILINE)
            parsed = json.loads(clean.strip())
        except Exception:
            pass
    # Attempt 3: extract first {...} block
    if not parsed:
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
        except Exception:
            pass
    if not parsed:
        logger.error("Banner prompt raw response: %s", raw[:500] if raw else "empty")
        return {"code": 500, "msg": "Gemini returned invalid JSON for banner prompt", "imagen_prompt": None, "best_frame_index": 0, "usage": res.get("usage", {})}

    # Gemini returned valid JSON but no edit prompt — frame had no person (quality=none).
    # Automatically fall through to product image fallback instead of erroring.
    if not parsed.get("imagen_prompt"):
        logger.info("Banner: no edit prompt returned (quality=%s, person_visible=%s) — switching to product fallback",
                    parsed.get("quality"), parsed.get("person_visible"))
        return _build_banner_prompt_product_fallback(params, contact_sheet, frame_count, category, ad_style, has_logo)

    best_frame_number = max(1, int(parsed.get("best_frame_number") or 1))
    raw_idx  = best_frame_number - 1
    best_idx = raw_idx if (0 <= raw_idx < frame_count) else max(0, frame_count // 2)

    quality           = parsed.get("quality", "none")
    best_frame_score  = int(parsed["best_frame_score"]) if parsed.get("best_frame_score") is not None else None
    frame_pick_reason = parsed.get("frame_pick_reason", "no reason returned")

    def _to_bool(v):
        if isinstance(v, bool):
            return v
        return str(v).lower() not in ("false", "0", "no")

    person_visible  = _to_bool(parsed.get("person_visible",  True))
    product_visible = _to_bool(parsed.get("product_visible", True))

    logger.info(
        "Frame picker: %d frames | picked cell #%d (idx %d) | score: %s/7 | quality: %s | person: %s | product: %s",
        frame_count, best_frame_number, best_idx, best_frame_score, quality,
        "yes" if person_visible else "NO", "yes" if product_visible else "NO",
    )

    return {
        "code":             0,
        "msg":              "success",
        "imagen_prompt":    parsed["imagen_prompt"],
        "best_frame_index": best_idx,
        "best_frame_score": best_frame_score,
        "quality":          quality,
        "person_visible":   person_visible,
        "product_visible":  product_visible,
        "text_specs":       parsed.get("text_specs"),
        "usage":            res["usage"],
    }


def _build_banner_prompt_product_fallback(params, contact_sheet, frame_count, category, ad_style, has_logo):
    logo_rule = "The logo will be composited separately — do NOT describe any logo in the overlay prompt." if has_logo else ""

    prompt = f"""You are an advertising creative director. No suitable video frame was found (no frame had both a person and product clearly visible). You are now selecting the best standalone PRODUCT IMAGE to use as the banner background.

You are viewing a contact sheet of {frame_count} product image(s) for a "{category}" advertisement in "{ad_style}" style. Each image has its NUMBER in the top-left corner.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 1 — PICK THE HERO PRODUCT IMAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP A — CATEGORY MATCH: For EACH numbered image, ask "Does this product BELONG to the '{category}' category?"
  Mark each image: MATCHES or DOES NOT MATCH.

STEP B — SELECT FROM MATCHES:
  • If ONE image matches → pick it.
  • If MULTIPLE match → pick the one with the cleanest photo presentation.
  • If NO image matches the category → pick the image that looks most like a packaged consumer product.

Return its 1-based cell number as "best_frame_number".
Set "best_frame_score" to 5. Set "quality" to "good". Set "person_visible" to false. Set "product_visible" to true.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 2 — TEXT CONTENT & PLACEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A) HEADLINE (2–3 words, ALL CAPS)
B) BRAND NAME — from product packaging. If unreadable, write "".
C) TAGLINE — "[Brand] — [2–3 word benefit]". 4–7 words total.
D) PLACEMENT — default "top_bottom". Use "side_left" or "side_right" only if product occupies < 40% of frame width.
E) COLOUR — from product packaging dominant accent colour; do NOT default to white.
F) DROP SHADOW — true if text zone is light or mid-tone.
{logo_rule}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK 3 — WRITE THE GPT IMAGE 2 EDIT PROMPT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is a product photo — there is NO person to preserve.
Write a GPT Image 2 prompt in EXACTLY this 3-sentence structure. Total 40–70 words.

SENTENCE 1: "This is a photo editing task only — do not alter the product, background, lighting, or composition in any way; the photograph must remain pixel-for-pixel identical except for the text additions below."
SENTENCE 2: Add the headline text in the appropriate font and colour at the top or bottom strip.
SENTENCE 3: Add the tagline in a smaller complementary weight below (or above) the headline.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPOND IN VALID JSON ONLY — NO PROSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "best_frame_number": <integer, 1-based cell number>,
  "best_frame_score":  5,
  "quality":           "good",
  "person_visible":    false,
  "product_visible":   true,
  "frame_pick_reason": "<explanation>",
  "imagen_prompt":     "<GPT Image 2 edit prompt>",
  "text_specs": {{
    "headline":        "<HEADLINE TEXT>",
    "brand_name":      "<brand name or empty string>",
    "tagline":         "<tagline>",
    "placement":       "<top_bottom|side_left|side_right|tight_crop>",
    "headline_color":  "<#HEX>",
    "tagline_color":   "<#HEX>",
    "drop_shadow":     <true|false>
  }}
}}"""

    res = _call_gemini(prompt, [contact_sheet])
    if res["code"] != 0:
        return {"code": 500, "msg": res["msg"], "imagen_prompt": None, "best_frame_index": 0, "usage": res.get("usage", {})}

    raw = res["raw"]
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        pass
    if not parsed:
        try:
            clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            clean = re.sub(r"```\s*$", "", clean, flags=re.MULTILINE)
            parsed = json.loads(clean.strip())
        except Exception:
            pass
    if not parsed:
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
        except Exception:
            pass

    if not parsed or "best_frame_number" not in parsed:
        logger.error("Product fallback banner raw response: %s", raw[:500] if raw else "empty")
        return {"code": 500, "msg": "Product fallback picker returned bad JSON", "imagen_prompt": None, "best_frame_index": 0, "usage": res.get("usage", {})}

    best_frame_number = int(parsed.get("best_frame_number") or 1)
    raw_idx  = best_frame_number - 1
    best_idx = max(0, min(raw_idx, frame_count - 1))

    logger.info("Product fallback picker: %d product(s) | picked cell #%d (idx %d)", frame_count, best_frame_number, best_idx)

    return {
        "code":             0,
        "msg":              "success",
        "imagen_prompt":    parsed.get("imagen_prompt", ""),
        "best_frame_index": best_idx,
        "best_frame_score": 5,
        "quality":          "good",
        "person_visible":   False,
        "product_visible":  True,
        "text_specs":       parsed.get("text_specs"),
        "usage":            res["usage"],
    }
