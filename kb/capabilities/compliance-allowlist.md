---
id: compliance-allowlist
title: Compliance and capability claims — the only sentences the bot may assert
category: capabilities
source: kb/products/pouches.md + kb/products/beef-jerky-bags.md + kb/products/boxes.md + kb/products/labels.md + kb/products/labels-bottle-wine-spirits.md + kb/products/boxes-campaign-styles.md + kb/materials/materials-by-family.md + kb/materials/pouches-mylar-materials-finishes.md + kb/materials/boxes-campaign-materials.md + kb/materials/extras.md + kb/facts/boxes-campaign-faq.md + kb/facts/design-support.md (all status: verified)
status: draft
last_reviewed: 2026-10-30
approver: pending — production drafts, counsel or owner approves (PLAN_V2 D-10)
---

# What this file is

PLAN_V2 §4.5: presence in the KB is **not** a licence to assert. The KB is full of marketing prose —
"weatherproof", "smell-proof", "cosmetic and food-grade (SBS)" — and a grounding rule based on "the
phrase appears somewhere in the KB" would let the model lift a campaign adjective into a compliance
claim. So compliance and capability claims get their own tier, stricter than the registry:

- A claim is assertable **only** if it appears in the `allowed` table below, in the wording given,
  scoped to the family given.
- Anything else → **BLOCK** `unsupported_claim`, and the bot uses the fixed deflection at the bottom
  of this file.
- Explaining **why** an option suits a product stays allowed without a row here ("a straight-walled
  rigid box keeps a glass jar from tipping"); asserting a **property** does not ("so it is food safe").

Two drafting rules that every row obeys:

1. **The source wording wins.** Where two verified files phrase the same thing differently, the row
   keeps both, separately, and says never merge. Example: the site says *FDA-approved food-grade
   materials … on demand* ([pouches.md](../products/pouches.md)) while the internal sales script says
   *FDA-compliant materials, interior linings and inks*
   ([materials-by-family.md](../materials/materials-by-family.md)). Neither may be rewritten into the
   other, and the script version must be introduced as a script rule, because that file says so.
2. **No number, standard, body or certificate that is not printed in a verified file.** The KB names
   no test standard, no certification body and no certificate number anywhere
   ([facts/design-support.md](../facts/design-support.md): "These are memberships, not product
   certifications, and no certificate numbers are shown"). So the bot never produces one.

# Allowed claims

Format: `topic|family|say|source|never_say`. Cells are separated by `|`; a list inside a cell uses
`;`; commas are ordinary text. `family: any` means the row is not family-scoped.

```capability
# table: allowed
# topic|family|say|source|never_say
food-contact|bags|Jerky bags are food-grade for direct contact.|kb/materials/pouches-mylar-materials-finishes.md; kb/products/beef-jerky-bags.md|Never extend food-grade beyond the jerky line; never upgrade it to food safe or FDA approved; never apply it to a pouch the customer names unless the jerky row covers it.
food-contact|bags|FDA-approved food-grade materials are used on demand for food packaging.|kb/products/pouches.md|Keep "on demand" — it is a request, not a default. Never say all our pouches are FDA approved, never drop "on demand", never name a certificate or standard.
food-contact|boxes|SBS paperboard is the board line used for cosmetic and food-grade boxes.|kb/materials/boxes-campaign-materials.md; kb/products/boxes-campaign-styles.md|Never say SBS is food safe or FDA approved — the source names a use, not a certification. This is the exact R15 case in PLAN_V2 §15.
food-contact|boxes|Food boxes use 14-16pt lightweight, 18-20pt standard and 24pt heavy-duty board.|kb/products/boxes.md|These are board grades, not a safety claim. Never present a gauge as food certification.
food-contact|any|Script rule, from our internal sales guidance: food packaging uses FDA-compliant materials, interior linings and inks.|kb/materials/materials-by-family.md|Always introduce it as a script rule — that file says so. Never merge it with the site's FDA-approved sentence, never present it as site-published.
food-contact|any|Script rule: food-safe coatings include polyethylene, wax coatings, PLA and aqueous coating.|kb/materials/materials-by-family.md|A named coating is not a claim that a specific job carries it. Never say a given box or pouch is food safe.
moisture|bags|Do not store items containing more than 10 percent moisture in mylar pouches — this is a category rule, not a guarantee for a specific product; food use is confirmed with the team.|kb/products/pouches.md|Never turn it into a clearance for the customer's product, never drop the confirm-with-the-team clause, never quote a moisture figure other than 10 percent.
barrier|bags|Mylar pouches use high-barrier film that blocks oxygen, moisture and light.|kb/materials/pouches-mylar-materials-finishes.md; kb/products/pouches.md|Never quote a barrier test value, layer stack or micron spec — the source states none. Never say weatherproof or smell-proof (see the never table).
barrier|bags|High-barrier metalized foil gives maximum protection against oxygen and light for long-term storage.|kb/products/pouches.md|Keep it to oxygen and light; the source does not claim moisture or odour protection for this film.
heat|bags|Let hot food cool before sealing: barrier film handles warmth but extreme heat can melt the inner layer, so fill at room temperature for long-term storage.|kb/products/pouches-mylar-filling-use.md|Never give a temperature number — none is stated. Never promise a hot-fill capability.
sealing|bags|Heat-seal with a standard commercial impulse sealer, steady pressure for about two seconds above the zipper line, creating an airtight, tamper-evident seal until the consumer tears the notch.|kb/products/pouches-mylar-filling-use.md|Tamper-evidence here describes that seal, not the pouch as a certified tamper-evident product.
child-resistance|bags|Child-resistant zippers use a two-step motion — squeeze both sides, then slide — and certified child-resistant zippers require two-handed strength.|kb/products/pouches.md|Never claim certification for a specific order, never name a standard, body or certificate number, never say child-proof.
child-resistance|bags|Child-Guard zippers are also offered among the bag extras.|kb/materials/extras.md|Child-Guard and child-resistant are listed separately in the sources; never merge them into one claim.
tamper-evidence|boxes|Pharmaceutical boxes can include braille embossing, custom die-cut foam or cardboard inserts, tamper-evident glue patterns and perforated tear strips.|kb/products/boxes.md|Scoped to pharmaceutical boxes as named options. Never generalise to every box style, never call it a tamper-evident certification.
sustainability|boxes|Sustainable options include biodegradable inks and recycled paper.|kb/facts/boxes-campaign-faq.md; kb/materials/boxes-campaign-materials.md|Never say recyclable, compostable, plastic-free or curbside recyclable — no source states any of them.
sustainability|boxes|Kraft paperboard 18-24pt is the eco-friendly retail packaging option.|kb/materials/boxes-campaign-materials.md|A material description, not a certification. Never attach a standard or a percentage of recycled content.
sustainability|bags|Script rule: water-based inks with nearly zero VOC emission are used for mylar printing.|kb/materials/materials-by-family.md|Introduce as a script rule. Never quote a VOC figure other than "nearly zero", never claim a certification.
sustainability|bags|Script rule: mylar eco options are PLA (polylactic acid) and compostable multi-layer structures.|kb/materials/materials-by-family.md|These are named material options, not a claim that a given pouch is compostable. Never say certified compostable.
water-resistance|labels|Clear labels are made from durable BOPP film, are water-resistant and scratch-resistant, and suit glass and plastic jars and bottles.|kb/products/labels-bottle-wine-spirits.md|Water-resistant, not waterproof. Never add dishwasher safe, freezer safe or submersion claims.
water-resistance|labels|Vinyl is used for abrasion resistance and outdoor use and is highly resistant to water and sun.|kb/products/labels.md|Never say waterproof or UV-proof; the source says highly resistant.
water-resistance|labels|For products that face water or oils, BOPP or vinyl with a gloss or matte laminate is usually recommended.|kb/products/labels.md; kb/products/labels-bottle-wine-spirits.md|A recommendation, not a guarantee. Never promise oil-proof or grease-proof performance.
water-resistance|labels|Vinyl is weatherproof and flexible and handles oils and moisture, in gloss or matte.|kb/products/labels-bottle-wine-spirits.md|"Weatherproof" is sourced for vinyl labels only — never extend it to mylar pouches, where it is marketing wording with no test data.
membership|banners|We are a registered member of the Printing United Alliance.|kb/facts/design-support.md|A membership, not a certification. Never say certified by, accredited by, or ISO/GMP/HACCP registered.
membership|any|Our About page lists FPA, NCA, SFA and the Central Fort Bend Chamber of Commerce.|kb/facts/design-support.md|Verify the acronym before using it — the NCA acronym differs from the INCA name in older notes. Never call any of these a certification body that certified a product.
```

# Never say — sourced bans

Each row is a phrase that **does** appear in our own material or is a natural upgrade of an allowed
row, and is banned anyway. `why` carries the source that bans it, so the guard can explain the block.

```capability
# table: never
# claim|family|why
weatherproof|bags|The campaign hero calls mylar pouches weatherproof, but the source file records it as campaign marketing wording with no test data in the repo (kb/materials/pouches-mylar-materials-finishes.md).
smell-proof|bags|Same source: llms.txt calls them smell-proof — marketing wording, no test data, so it is not assertable.
odor-proof / odour-proof|bags|Same ban as smell-proof; a spelling variant is not a new source.
food safe|any|No verified file uses the phrase. The sourced words are food-grade for the jerky line and FDA-approved food-grade materials on demand.
FDA approved / FDA approved facility|any|The site sentence is about materials used on demand for food packaging (kb/products/pouches.md). Nothing states the facility is FDA registered or approved.
FDA certified|any|No source. FDA does not certify packaging; the KB never claims it.
BPA-free|any|The word BPA appears nowhere in the verified KB.
child-proof|bags|The sourced term is child-resistant, and certification is only described for certified zippers requiring two-handed strength. Never upgrade resistant to proof.
certified child-resistant for your order|bags|Certification is described as a property of certified zippers in general (kb/products/pouches.md), not as something the bot may promise for a specific job.
recyclable|any|No source states recyclability for any product. The sourced sustainability words are biodegradable inks and recycled paper for boxes.
compostable (as a property of a job)|bags|Compostable multi-layer is a named material option in the internal script, not a claim about a finished pouch. No certification is named.
biodegradable (as a property of a pouch or box)|any|Biodegradable is sourced only for inks on boxes (kb/facts/boxes-campaign-faq.md; kb/materials/boxes-campaign-materials.md).
plastic-free|any|No source.
curbside recyclable|any|No source.
waterproof|labels|The sourced words are water-resistant (BOPP clear labels) and highly resistant to water and sun (vinyl). "Weatherproof" is sourced for vinyl labels only.
dishwasher safe / freezer safe / microwave safe|any|No source for any of them.
oil-proof / grease-proof|labels|The sourced wording is that vinyl handles oils and moisture, and that BOPP or vinyl with laminate is usually recommended for water or oil exposure.
barrier test value / OTR / WVTR number|bags|The source states no layer stack, micron spec, valve or barrier test value (kb/materials/pouches-mylar-materials-finishes.md).
micron spec presented as a guarantee|bags|80-150 micron is a pouch-page film range and 5-7 mil is a recommendation for sharp or heavy products; neither is a performance guarantee, and the two figures are never merged.
ISO 9001 / GMP / HACCP / FSC certified|any|No certification of any kind is named in the verified KB. FSC appears once, as FSC-compliant paperboard used for mushroom products in the internal script (kb/materials/materials-by-family.md) — a script line about one category, not a company certification, so it is not assertable without sales confirmation.
certificate number|any|No certificate numbers are shown anywhere (kb/facts/design-support.md).
guaranteed / guaranteed fit / guaranteed shelf life|any|Sizes and capacities in the KB are listing values and guides, and the KB itself says never present a capacity as a guarantee.
```

# Fixed deflection

When a claim is outside the `allowed` table, the bot does not improvise a softer version of it. It
says the property is confirmed with the quote, and keeps helping:

> Material and compliance specs are confirmed by our team with your quote — tell me what the product
> is and how it ships, and I will get the right options in front of them.

The deflection is the whole answer to a compliance question. It is not a licence to then assert the
claim anyway in the next sentence, and §4.5's rule still holds: the bot may explain **why** an option
suits the product, using general packaging knowledge, without naming a property we have not signed.

# Open items

1. **Named approver (D-10).** `approver:` in the frontmatter is `pending`. Production drafts, counsel
   or the owner approves; the name goes on the file before any row is assertable in live v2.
2. **Two claims need a decision, not a source.** (a) Is the jerky line's "food-grade for direct
   contact" the only food-contact claim sales wants made in chat, or should the FDA-approved
   materials sentence carry it for other pouch lines? (b) The script says label stock is *PP white
   vinyl only* while the site lists six label materials — that conflict is in the registry's
   `needs_production_answer`, and until it is resolved the water-resistance rows above are the only
   label property claims the bot may make.
3. **FSC-compliant paperboard** for mushroom products is deliberately **not** an allowed row: it is
   one line in the internal script about one category, and turning it into a claim is exactly the
   marketing-to-compliance lift §4.5 exists to stop. If production wants it assertable, it gets a row
   with a name against it.
