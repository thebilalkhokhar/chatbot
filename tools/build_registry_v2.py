"""Write kb/capabilities/capability-registry.md from the kb_v2 corpus.

One-shot generator, kept in the repo so the registry's provenance is reproducible:
`python chatbot/tools/build_registry_v2.py > ../kb/capabilities/capability-registry.md`

Everything it emits is either a verbatim catalogue string (with the file that carries it) or a
row typed out in the DATA section below, where the citations are the ones the kb_v2 inventories
collected. Values are folded to one canonical form per concept by MERGE, and the fold is
repeatable rather than hand-typed, because the same phrase reaches us as "Softouch",
"Soft Touch" and "soft-touch" on different pages.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("extract", ROOT / "chatbot" / "tools" / "extract_capabilities.py")
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)

ACRONYMS = {"PE", "PP", "PET", "PVC", "PLA", "ABS", "SBS", "BOPP", "NFC", "QR", "UV", "CMYK", "PMS",
            "FDA", "MOQ", "3D", "ID", "PETG", "AQ", "IPPC"}

# Written variants the corpus uses for one concept -> the canonical cell the registry stores.
MERGE = {
    "gloss laminated": "gloss lamination",
    "gloss laminate": "gloss lamination",
    "matte laminated": "matte lamination",
    "matte laminate": "matte lamination",
    "softtouch": "soft touch",
    "soft-touch": "soft touch",
    "soft touch lamination": "soft touch lamination",
    "softtouch lamination": "soft touch lamination",
    "soft-touch lamination": "soft touch lamination",
    "drip-off": "drip off",
    "spotuv": "spot UV",
    "spot gloss": "spot gloss",
    "spot matte": "spot matte",
    "spot foil": "spot foiling",
    "spot foiling": "spot foiling",
    "hot-stamp foiling": "hot foil stamping",
    "hot stamp": "hot foil stamping",
    "hot foil stamping": "hot foil stamping",
    "3 dimensional raised uv effects": "3D raised UV",
    "3d raised uv": "3D raised UV",
    "raised uv": "3D raised UV",
    "3 dimensional raised uv": "3D raised UV",
    "gloss uv": "gloss UV",
    "matte uv": "matte UV",
    "uv coating": "UV coating",
    "uv": "UV coating",
    "sheen aqueous": "aqueous coating",
    "aqueous": "aqueous coating",
    "aq coating": "aqueous coating",
    "varnishing": "varnish",
    "die cutting": "die cut",
    "die-cut": "die cut",
    "kiss cutting": "kiss cut",
    "reverse printing": "reverse printing",
    "inside-glass": "reverse printing",
    "anti-scratch lamination": "anti-scratch lamination",
    "inside printing": "inside printing",
    "tactile feel": "tactile feel",
    "debossing": "debossing",
    "deep embossing": "deep embossing",
    "deep debossing": "deep debossing",
    "corrugated": "corrugated board",
    "corrugated board": "corrugated board",
    "corrugated stock": "corrugated board",
    "corrugated substrates": "corrugated board",
    "corrugated cardboard": "corrugated cardboard",
    "grayboard": "grayboard",
    "greyboard": "grayboard",
    "rigid grayboard": "grayboard",
    "buxboard": "bux board",
    "rigid stocks": "rigid board",
    "rigid": "rigid board",
    "rigid board": "rigid board",
    "e flute": "e-flute",
    "e-flute corrugated": "e-flute",
    "corrugated e-flute": "e-flute",
    "polyethylene": "PE",
    "polypropylene": "PP",
    "polyethylene terephthalate": "PET",
    "polyester fabric": "polyester fabric",
    "transparent polyester": "polyester",
    "corrugated plastics": "corrugated plastic",
    "corflute": "corrugated plastic",
    "metallized film layer": "metallized film",
    "high-barrier metalized foil": "metalized foil",
    "paper": "paper",
    "perforations": "perforation",
    "handles": "handle",
    "carry handles": "handle",
    "lift tabs": "lift tab",
    "tabs": "lift tab",
    "vent holes": "vent hole",
    "resealable tabs": "resealable tab",
    "ribbon pulls": "ribbon pull",
    "cut outs": "cut-out",
    "cut-outs": "cut-out",
    "euro holes": "Euro hole",
    "hang holes": "hang hole",
    "foam inserts": "foam insert",
    "molded pulp trays": "molded pulp tray",
    "paperboard dividers": "paperboard divider",
    "velvet-lined trays": "velvet-lined tray",
    "tamper-evident features": "tamper-evident seal",
    "child-resistant zippers": "child-resistant zipper",
    "easy-open zippers": "easy-open zipper",
    "easy open zippers": "easy-open zipper",
    "magnetic closures": "magnetic closure",
    "raised inks": "raised ink",
    "led light modules": "LED light module",
    "stackable designs": "stackable design",
    "layered reveal mechanisms": "layered reveal mechanism",
    "colour customization": "colour customization",
    "color customization": "colour customization",
    "full bleed": "full bleed",
    "white border": "white border",
    "no border": "no border",
    "white cardboard": "white cardboard",
    "silver cardboard": "silver cardboard",
    "holographic cardboard": "holographic cardboard",
    "rigid cardboard": "rigid cardboard",
    "recycled paperboard": "recycled paperboard",
    "double coated card stock": "double coated card stock",
    "gloss paper": "gloss paper",
    "textured paper": "textured paper",
    "textured papers": "textured paper",
    "kraft board": "kraft board",
    "foamcore": "foamcore",
    "static cling": "static cling",
    "acetate": "acetate",
    "nylon": "nylon",
    "mylar": "mylar",
    "foil": "foil",
    "foil pouch": "foil pouch",
    "foil printing": "foil printing",
    "gold foiling": "foil printing",
    "holographic foil printing": "holographic foil printing",
    "holographic foil": "holographic foil",
    "holographic": "holographic",
    "metalized": "metalized",
    "embossing": "embossing",
    "matte": "matte",
    "gloss": "gloss",
    "glossy": "gloss",
    "plain white": "plain white",
    "window": "window",
    "clear window": "window",
    "zipper": "zipper",
    "tear notch": "tear notch",
    "satin": "satin",
    "textured": "textured",
    "lamination": "lamination",
    "grommets": "grommets",
    "pole pockets": "pole pockets",
    "reinforced corners": "reinforced corners",
    "weather-proof stock": "weatherproof stock",
    "heat-welded hem": "heat-welded hem",
    "double-sided": "double-sided",
    "single-sided": "single-sided",
    "numbering": "numbering",
    "variable data": "variable data",
    "qr code": "QR code",
    "nfc tap profile": "NFC tap profile",
    "degassing valve": "degassing valve",
    "press-to-close zipper": "press-to-close zipper",
    "easy-open standard zipper": "easy-open zipper",
    "perforated tear strip": "perforated tear strip",
    "tamper-evident glue pattern": "tamper-evident seal",
    "die-cut cardboard insert": "die-cut cardboard insert",
    "die-cut foam insert": "foam insert",
    "braille embossing": "braille embossing",
    "any pantone colour": "any Pantone colour",
    "eco-friendly ink": "eco-friendly ink",
    "sauce cup insert": "sauce cup insert",
    "copper foil": "copper foil",
    "foil gold": "gold foil",
    "gold foil": "gold foil",
    "foil rose": "rose gold foil",
    "rose-gold foil": "rose gold foil",
    "foil silver": "silver foil",
    "heat-sealed": "heat seal",
    "rigid chipboard": "rigid chipboard",
    "kraft film": "kraft film",
    "kraft paper laminate": "kraft paper laminate",
    "kraft paperboard": "kraft paperboard",
    "kraft": "kraft",
    "compostable multi-layer": "compostable multi-layer",
    "holographic film": "holographic film",
    "silver film": "silver film",
    "clear film": "clear film",
    "clear/transparent film": "clear film",
    "cardstock": "cardstock",
    "card board": "cardboard",
    "white paper": "white paper",
    "paperboard": "paperboard",
    "sbs paperboard": "SBS paperboard",
    "sbs": "SBS paperboard",
    # Parenthetical expansion attested in kb/materials/boxes-campaign-materials.md.
    "solid bleached sulfate": "SBS paperboard",

    "acrylic": "acrylic",
    "vinyl": "vinyl",
    "bopp": "BOPP",
    "pet": "PET",
    "pe": "PE",
    "pp": "PP",
    "pvc": "PVC",
    "pla": "PLA",
    "abs": "ABS",
    "mylar bags": "mylar bag",
}

# --- hand-authored rows (citations are the kb_v2 files that carry the wording) -------------------

FAMILY_LABEL = {
    "boxes": "Boxes & packaging", "bags": "Mylar bags & pouches", "labels": "Labels & stickers",
    "banners": "Signs & banners", "business_cards": "Business cards", "print": "Print products",
}

# family|kind|style|material|insert|finish|extras|reason|source|approved
EXCLUDED: list[tuple[str, ...]] = [
    ("labels", "rule", "clings", "-", "-", "-", "-",
     "static cling will not hold on textured or porous walls; the electrostatic grip drops and the edge lifts",
     "kb_v2/catalog/catalog-clings.md", "pending"),
    ("banners", "rule", "-", "-", "-", "-", "-",
     "car-window clings must not sit in the driver's direct line of sight (safety, not capability)",
     "kb_v2/catalog/catalog-clings.md", "pending"),
    ("labels", "rule", "-", "-", "-", "-", "-",
     "front-adhesive decals are refused on textured or porous surfaces; the adhesive needs a clean flat surface",
     "kb_v2/catalog/catalog-front-adhesive-stickers.md", "pending"),
    ("labels", "rule", "front-adhesive stickers", "-", "-", "-", "-",
     "vinyl front-adhesive is one-time application; it loses its stick once removed, so reuse is not offered",
     "kb_v2/catalog/catalog-front-adhesive-stickers.md", "pending"),
    ("labels", "rule", "window decals", "-", "-", "-", "reuse",
     "sticky vinyl decals are for long-term application and are not re-usable; only static cling is",
     "kb_v2/catalog/catalog-window-decals.md", "pending"),
    ("labels", "rule", "-", "paper", "-", "-", "-",
     "paper stock labels are not made for water or weather; wet use needs a synthetic stock",
     "kb_v2/catalog/catalog-cosmetic-labels.md", "pending"),
    ("labels", "rule", "specialty food labels", "-", "-", "-", "-",
     "we will not print a food label on stock that cannot withstand cold storage, oil or handling",
     "kb_v2/catalog/catalog-labels-stickers-specialty-labels.md", "pending"),
    ("boxes", "rule", "display boxes", "rigid cardboard", "-", "window", "-",
     "open-front display boxes are shelf units and are not durable for heavy shipping",
     "kb_v2/catalog/catalog-display-box-with-logo.md", "pending"),
    ("boxes", "rule", "-", "paperboard", "-", "-", "-",
     "paperboard alone does not control temperature; coatings only block moisture",
     "kb_v2/catalog/catalog-medicine-boxes.md", "pending"),
    ("boxes", "rule", "-", "-", "foam insert", "-", "-",
     "precision foam inserts suit uneven bottles but the page warns they hurt the pack's recyclability",
     "kb_v2/catalog/catalog-perfume-boxes.md", "pending"),
    ("business_cards", "rule", "-", "-", "-", "foil stamping", "-",
     "foil runs under 1,000 are refused for machine set-up, not price: print 1,000 and split the batch",
     "kb_v2/catalog/catalog-foil-accent-business-cards.md", "pending"),
    ("bags", "rule", "-", "foil", "-", "-", "-",
     "foil-lined structures are multi-layer and some recycling streams reject them, so no curbside claim",
     "kb_v2/catalog/catalog-child-resistant-pouches.md", "pending"),
    ("bags", "rule", "-", "mylar", "-", "deep debossing", "-",
     "thin film cannot hold a deep debossed impression; the hub limits it to thicker bags",
     "kb_v2/knowledge/know-mylar-bags-pouches-how-debossed-printing-works-on-mylar-packaging.md", "pending"),
    ("bags", "rule", "-", "-", "-", "-", "-",
     "flexographic printing is refused for short runs and for designs that keep changing (plate cost)",
     "kb_v2/knowledge/know-mylar-bags-pouches-when-to-use-flexographic-printing-for-packaging.md", "pending"),
    ("bags", "rule", "-", "-", "-", "-", "-",
     "flexographic printing is not quoted for photo-level sharp detail",
     "kb_v2/knowledge/know-mylar-bags-pouches-when-to-use-flexographic-printing-for-packaging.md", "pending"),
    ("bags", "rule", "-", "-", "-", "-", "press-to-close zipper",
     "a press-to-close zipper is not sold as a replacement for the original heat-seal barrier",
     "kb_v2/knowledge/know-mylar-bags-pouches-press-to-close-zipper-mylar-pouches.md", "pending"),
    ("bags", "rule", "-", "-", "-", "-", "-",
     "a standard sealed pouch is unsuitable for products that keep releasing gas (coffee) unless a "
     "degassing valve is added",
     "kb_v2/knowledge/know-mylar-bags-pouches-understanding-degassing-valves-in-mylar-bags.md", "pending"),
    ("bags", "rule", "-", "-", "-", "-", "-",
     "not every vacuum pouch is heat-safe; the hub says to check the product specification",
     "kb_v2/knowledge/know-mylar-bags-pouches-what-are-vacuum-pouches.md", "pending"),
    ("banners", "rule", "wall signs", "-", "-", "-", "-",
     "the wrinkle-free fabric sign grade is explicitly not recommended for exterior UV and rain",
     "kb_v2/knowledge/know-signs-and-banners-what-are-wall-signs-light-and-simple-guide-to-this-signage-in-everyday-life.md",
     "pending"),
    ("boxes", "rule", "pillow boxes", "-", "-", "-", "-",
     "pillow boxes are described as carrying small, light goods only, not heavy items",
     "kb_v2/knowledge/know-folding-cartons-pillow-boxes-when-minimalism-becomes-the-latest-trend.md", "pending"),
    ("boxes", "rule", "seal-end boxes", "-", "-", "-", "-",
     "a seal-end box is not meant for products the customer opens and closes repeatedly",
     "kb_v2/knowledge/know-folding-cartons-seal-end-box-packaging-a-brief-overview.md", "pending"),
    ("boxes", "rule", "-", "duplex board", "-", "-", "-",
     "duplex board is ruled out for very heavy or delicate products",
     "kb_v2/knowledge/know-folding-cartons-what-is-a-duplex-board-and-why-is-it-popular.md", "pending"),
    ("boxes", "rule", "-", "CCNB", "-", "-", "-",
     "CCNB is not offered for heavy-duty use",
     "kb_v2/knowledge/know-folding-cartons-clay-coated-news-back-ccnb-cost-effective-packaging.md", "pending"),
    ("boxes", "rule", "-", "lined paperboard", "-", "-", "-",
     "lined paperboard is not supported for heavy products",
     "kb_v2/knowledge/know-folding-cartons-what-is-lined-paperboard.md", "pending"),
    ("boxes", "rule", "-", "chipboard", "-", "-", "-",
     "chipboard cannot take very heavy weight; it is a shape-and-structure stock",
     "kb_v2/knowledge/know-folding-cartons-what-is-a-chipboard-and-what-role-does-it-play-in-packaging.md", "pending"),
    ("print", "rule", "-", "construction paper", "-", "-", "-",
     "construction paper is ruled out for detailed printing; the surface is rough",
     "kb_v2/knowledge/know-folding-cartons-what-is-construction-paper.md", "pending"),
]

# family|values|note|source  (`values` holds only sizes the site actually publishes; prose goes in `note`)
SIZES: list[tuple[str, ...]] = [
    ("boxes", "-",
     'no size grid and no standard: pages answer "any size and any shape" or "custom sizes and '
     "measurements\", so a box size comes from the visitor or from Sales; the only figures in the corpus "
     "are cake boxes up to 14 in and pie boxes 9-12 in",
     "kb_v2/catalog/catalog-christmas-gift-boxes.md; kb_v2/catalog/catalog-category-food-beverage-boxes.md"),
    ("bags", "-",
     "no size grid: the corpus names sizes in words (small, large, extra large) and lists fill capacities "
     "1 oz to 32 oz under Materials on the stand-up pouch page, never as a size table, so a capacity figure "
     "is not a size and must not be quoted as one",
     "kb_v2/catalog/catalog-christmas-gift-bags.md; kb_v2/catalog/catalog-stand-up-pouch.md"),
    ("labels", "-",
     'no size grid: pages say "Standard & Custom Sizes", "Fully Custom (Any Shape & Size)" and '
     '"Custom Width & Height" without a standard list to read from',
     "kb_v2/catalog/catalog-product-labels.md; kb_v2/catalog/catalog-custom-shape-labels.md; "
     "kb_v2/catalog/catalog-window-decals.md"),
    ("business_cards", "-",
     'no size row on any card page: the standard card page answers "Dimensions (LxH): Any custom sizes '
     'and measurements" and no page prints 3.5 x 2 in, so a card size comes from the visitor',
     "kb_v2/catalog/catalog-standard-business-card.md"),
    ("banners", '23" x 66"; 24" x 81"; 33" x 81"; 47" x 81"',
     "pull-up banners are the only published size list in the corpus; every other sign page answers custom "
     'width and height, and "or custom" is offered alongside these four',
     "kb_v2/catalog/catalog-pull-up-banners.md; kb_v2/catalog/catalog-window-decals.md"),
    ("print", '3.5" x 8.5"; 3.5" x 11"',
     "tear-card sizes are spec bullets; door-hanger sizes (3.5\" x 8.5\", 4.25\" x 11\", 5.5\" x 17\") appear "
     "only in FAQ prose while the page's own Sizes section says none is published, so they are not listed "
     "here; no other print product publishes a size",
     "kb_v2/catalog/catalog-custom-tear-cards.md; kb_v2/catalog/catalog-door-hanger.md"),
]

# family|material|gauge|basis|source|note
GAUGES: list[tuple[str, ...]] = [
    ("boxes", "kraft board", "80 lb to 100 lb", "page",
     "kb_v2/catalog/catalog-tuck-boxes.md", "spec bullet, same wording on the food & beverage category page"),
    ("boxes", "rigid paperboard", "800 to 1200 gsm", "faq",
     "kb_v2/catalog/catalog-tuck-boxes.md", "the only gsm range the corpus attaches to a named box stock"),
    ("boxes", "corrugated board, bux board, grayboard, cardstock, kraft", "12 pt to 28 pt (60 lb to 400 lb)",
     "page", "kb_v2/catalog/catalog-custom-hoodie-packaging.md",
     "one bullet covers the whole stock list; the source never splits the range by material"),
    ("boxes", "paperboard", "12 pt to 28 pt", "faq", "kb_v2/catalog/catalog-cbd-cream-boxes.md",
     'the answer says "usually around" and calls it customizable; it names no material'),
    ("boxes", "rigid cardboard and paperboard", "18 pt to 24 pt", "faq",
     "kb_v2/catalog/catalog-tea-bag-dispenser.md", "stated for crush resistance"),
    ("business_cards", "cardstock", "13 pt, 14 pt, 16 pt, 18 pt", "page",
     "kb_v2/catalog/catalog-standard-business-card.md", "spec bullets; the page's Materials list is multi-material"),
    ("business_cards", "cardstock", "12 pt, 14 pt or 16 pt, 18 pt or 24 pt", "faq",
     "kb_v2/catalog/catalog-folded-business-card.md", "advice by use (bulk mailer / pocket / premium)"),
    ("business_cards", "cardstock", "32 pt", "page", "kb_v2/catalog/catalog-ultra-thick-business-cards.md",
     "also 32 pt linen on the linen page and 32 pt raised foil on the premium page"),
    ("business_cards", "coated board", "16 point", "faq", "kb_v2/catalog/catalog-embossed-gloss-business-cards.md",
     "the same answer gives 20 mil PVC or PETG for the plastic version"),
    ("business_cards", "PVC, PETG", "20 mil", "faq", "kb_v2/catalog/catalog-embossed-gloss-business-cards.md",
     "water and tear resistance"),
    ("business_cards", "cardstock (tent cards)", "12 to 24 point", "knowledge",
     "kb_v2/knowledge/know-business-cards-tent-card-standing-business-card-guide.md",
     "hub article, not a product page"),
    ("print", "gloss paper, high-finish and uncoated paper", "70 lb to 100 lb", "page",
     "kb_v2/catalog/catalog-brochures.md", "same wording on the political brochure page"),
    ("print", "high-finish and uncoated paper", "60 lb to 75 lb", "page", "kb_v2/catalog/catalog-booklets.md",
     "the page names no paper type beyond that"),
    ("print", "cardstock", "10 pt", "page", "kb_v2/catalog/catalog-custom-political-postcards.md",
     "adjacent Materials bullet"),
    ("bags", "metallized film", "5 mil", "faq", "kb_v2/catalog/catalog-pre-roll-mylar-bags.md",
     "stated as an oxygen, moisture and UV barrier"),
    ("bags", "metallized film", "120 micron", "faq", "kb_v2/catalog/catalog-vape-pouches.md",
     'named as beating the "high barrier" oxygen threshold'),
    ("bags", "laminate", "80 micron", "faq", "kb_v2/catalog/catalog-vape-pouches.md", "single-pod promo weight"),
    ("bags", "foil", "80 micron", "faq", "kb_v2/catalog/catalog-flat-bottom-pouches.md",
     "quoted inside a coffee shelf-life comparison"),
    ("bags", "compostable and recyclable constructions", "80 to 150 micron", "faq",
     "kb_v2/catalog/catalog-eco-friendly-pouches.md", 'the answer says "across most constructions"'),
    ("bags", "PE", "100 micron (about 4 mil) and 130 to 150 micron", "faq",
     "kb_v2/catalog/catalog-hemp-flower-mylar-bag.md",
     "split by pack size, not by material; the page's own Materials bullet is Metalized+Clear"),
    ("bags", "PET", "120 micron", "faq", "kb_v2/catalog/catalog-poly-mailers.md", "suggested for pointed parts"),
    ("banners", "vinyl", "13 oz, 18 oz", "faq", "kb_v2/catalog/catalog-step-and-repeat-banners.md",
     "matte stretch polyester is named alongside, without a weight"),
    ("banners", "scrim vinyl", "13 oz to 18 oz per square yard", "knowledge",
     "kb_v2/knowledge/know-signs-and-banners-what-are-scrim-vinyl-banners-durable-guide.md", "hub article"),
    ("banners", "mesh", "8 oz per yard", "knowledge",
     "kb_v2/knowledge/know-signs-and-banners-what-are-mesh-banners-and-why-theyre-taking-over-signs.md",
     "hub article, compared against 13 oz vinyl"),
    ("banners", "backlit vinyl", "15 to 20 oz per square yard", "knowledge",
     "kb_v2/knowledge/know-signs-and-banners-what-is-backlit-vinyl-and-what-does-it-mean.md", "hub article"),
    ("banners", "coroplast", "4 mm, 6 mm, 8 mm", "knowledge",
     "kb_v2/knowledge/know-signs-and-banners-what-are-corrugated-plastic-coroplast-compositions.md",
     "hub article; the yard-sign guide repeats 4 mm as standard"),
    ("banners", "PVC board / Sintra", "3, 5, 10, 19 mm", "knowledge",
     "kb_v2/knowledge/know-signs-and-banners-what-is-pvc-board-sintra-expanded-pvc-a-clear-guide-for-signs-and-banners.md",
     "hub article"),
    ("banners", "acrylic", "1/8 in to 1 in", "knowledge",
     "kb_v2/knowledge/know-signs-and-banners-what-are-acrylic-signs-how-they-deliver-real-efficiency.md",
     "hub article; 3/16 in and 1/4 in named as the popular sign thicknesses"),
    ("labels", "none published", "-", "-", "-",
     "no label, sticker or decal page in kb_v2 states a face-stock gauge in pt, mil, micron or gsm"),
]

# family|question|asked|source
NEEDS_PRODUCTION: list[tuple[str, ...]] = [
    ("banners", "which sign products are ours as a line: Signicades, desk name plates, restroom signs, "
                 "parking signs and A-frames are named by the signs category page but publish no specs",
     "sales and production", "kb_v2/catalog/catalog-signicades.md"),
    ("print", "coasters, mugs, keychains, envelopes, wall calendars, posters, numbered tickets and variable "
              "printing have pages but no specs and no category listing; are these live product lines?",
     "sales", "kb_v2/catalog/catalog-coaster.md; kb_v2/catalog/catalog-mugs.md; kb_v2/catalog/catalog-keychain.md"),
    ("boxes", "is supplements-packaging a seventh catalogue family or part of boxes? The site gives it its "
              "own category prefix and one page",
     "sales", "kb_v2/catalog/catalog-supplements-packaging.md"),
    ("bags", "which film constructions are actually stocked, and which gauge do we quote for a given pack "
             "size? Every gauge in the corpus is an FAQ answer that names no material or splits by size",
     "production", "kb_v2/catalog/catalog-hemp-flower-mylar-bag.md"),
    ("labels", "no label page publishes a face-stock thickness, so which stock do we quote for freezer, "
               "outdoor and UV exposure?", "production", "kb_v2/catalog/catalog-barcode-labels.md"),
    ("boxes", "flute profiles are listed with no thickness, ECT or ply figure anywhere in the corpus: what "
              "do we actually specify for E, B, C, EB and BC flute?", "production",
     "kb_v2/catalog/catalog-category-food-beverage-boxes.md"),
    ("print", "the mug page reads as a copyright condition but the sentence is garbled; can we repeat any "
              "copyright rule to a visitor?", "legal", "kb_v2/catalog/catalog-mugs.md"),
    ("bags", "is the published WVTR figure (below 0.1 g/m2/day) ours to state, and where is the test report?",
     "production and legal", "kb_v2/catalog/catalog-hemp-flower-mylar-bag.md"),
]

# family|value|note|class  (class `probe` rows are the deliberate negative probes the bot must fail)
NOT_ATTESTED: list[tuple[str, str, str, str]] = [
    ("boxes", "pillow box", "described generically in the folding-carton hub; no product page offers one, so "
                            "we do not say we make it", "probe"),
    ("boxes", "sleeve box", 'the phrase "Sleeves use 40% less material than full boxes" appears in FAQ prose '
                            "on a box category page; no sleeve product page exists", "probe"),
    ("boxes", "rigid mylar box", "mixes a bag material with a box form; neither page pairs them", "probe"),
    ("bags", "Child-Guard zipper", "the brand name does not appear anywhere in kb_v2; the mechanisms the site "
                                   "names are push-and-pull, push-and-slide, press-to-close and pinch-and-pull", "probe"),
    ("bags", "squeeze-then-slide zipper", "phrasing not in kb_v2; see the four mechanisms the site does name", "probe"),
    ("labels", "braille embossing", "in the v1 vocabulary; no label or card page in kb_v2 mentions braille", "probe"),
    ("print", "letterpress", "not in kb_v2; the print pages name offset, digital, screen and flexographic", "probe"),
]

# family|slot|values is generated; folds applied by canonical()

def _norm(text: str) -> str:
    """One comparison form for a written value: case, hyphens, slashes and separators folded away."""
    return re.sub(r"\s+", " ", re.sub(r"[-/_&,.:;+]", " ", text.lower())).strip()


# Values v1 carried in the wrong slot. The loader keeps a value in one slot no matter which `##` section
# a page prints it under, so a mislabel in the seed is permanent unless corrected here with a reason.
SLOT_FIX = {
    "foil pouch": ("material", "the site lists Foil Pouch under Materials as a bag structure, not a coating"),
    "plain white": ("colour", "an appearance of the stock; v1 carried it as a finish"),
}

MERGE = {_norm(_k): _v for _k, _v in MERGE.items()}


def canonical(value: str) -> str:
    key = _norm(value)
    if key in MERGE:
        return MERGE[key]
    words = [w.upper() if w.upper() in ACRONYMS else w for w in key.split()]
    text = " ".join(words)
    return {"uv": "UV", "3d": "3D"}.get(text, text)


def slot_of(found: str, lexicon: dict) -> str:
    fixed = SLOT_FIX.get(canonical(found))
    if fixed:
        return fixed[0]
    return (lexicon.get(extract.words(found)) or ("", ""))[1]


def main() -> int:
    lexicon, _ = extract.seed_lexicon()
    pages = [extract.read_page(p)
             for part in ("catalog", "site") for p in sorted((extract.CORPUS / part).rglob("*.md"))]
    styles = extract.site_families(pages)
    fold_lexicon = {k: v for k, v in lexicon.items() if v[1] == "fold"}

    rows: list[dict] = []
    values: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    unmapped: list[tuple[str, str, str]] = []

    for page in pages:
        title = page["meta"].get("title", page["stem"])
        url = page["meta"].get("source", "")
        kind = extract.page_kind(url, page["sections"])
        if kind in ("category", "deal", "other") and page["stem"].startswith("site-"):
            continue
        family, basis = extract.classify(title, url, styles)
        if not family:
            unmapped.append((page["stem"], title, kind))
            continue
        slots: dict[str, list[str]] = defaultdict(list)
        for section, _slot in extract.SLOT_SECTIONS.items():
            for bullet in page["sections"].get(section, []):
                for part in extract.candidates(bullet):
                    for found in extract.match_part(part, lexicon)[0]:
                        value, slot = canonical(found), slot_of(found, lexicon)
                        if value not in slots[slot]:
                            slots[slot].append(value)
                        values[family][slot][value] += 1
        # kb_v2 only names folds inside FAQ prose (brochures, folded cards), never as a spec bullet,
        # so the fold slot is read out of the FAQ text instead of being dropped.
        for bullet in page["sections"].get("FAQ", []):
            for found in extract.match_part(bullet, fold_lexicon)[0]:
                value = canonical(found)
                values[family]["fold"][value] += 1
        if kind == "product":
            rows.append({"family": family, "basis": basis, "page": page, "slots": dict(slots),
                         "style": canonical_style(title)})

    absent = missing_from_corpus()
    check_arity(values, absent)
    write(rows, values, unmapped, absent)
    return 0


TABLE_ARITY = {
    "vocabulary": 3, "supported": 11, "excluded": 10, "sizes": 4, "gauges": 6,
    "needs_production": 4, "not_attested": 4, "unmapped": 3,
}


def check_arity(values: dict, absent: list[tuple[str, str, str, str]]) -> None:
    """Fail loudly rather than write a table parse_tables will reject."""
    for name, rows in (("excluded", EXCLUDED), ("sizes", SIZES), ("gauges", GAUGES),
                       ("needs_production", NEEDS_PRODUCTION), ("not_attested", list(NOT_ATTESTED) + absent)):
        for row in rows:
            if len(row) != TABLE_ARITY[name]:
                raise SystemExit(f"{name}: {len(row)} cells, expected {TABLE_ARITY[name]}: {row[:3]}")
            for cell_text in row:
                if "|" in cell_text:
                    raise SystemExit(f"{name}: cell contains a pipe: {cell_text[:60]}")
    emitted = {"style", "material", "colour", "finish", "extras", "insert", "fold"}
    for family, slots in values.items():
        for slot, counter in slots.items():
            if slot not in emitted:
                raise SystemExit(f"vocabulary slot {slot!r} is not a column the writer emits "
                                 f"(seen on {family}: {list(counter)[:3]})")
            for value in counter:
                if "|" in value:
                    raise SystemExit(f"vocabulary {family}/{slot}: value contains a pipe: {value}")


def canonical_style(title: str) -> str:
    text = extract.clean(re.sub(r"^(custom|bespoke|printed)\s+", "", title, flags=re.I))
    return text[0].upper() + text[1:] if text else text


def cell(values: list[str]) -> str:
    return "; ".join(values) if values else "-"


def write(rows: list[dict], values: dict, unmapped: list, absent: list) -> None:
    fam_order = ["boxes", "bags", "labels", "business_cards", "banners", "print"]
    out = sys.stdout
    w = out.write
    per_family: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        per_family[row["family"]].append(row)

    w("---\n")
    w("id: capability-registry\n")
    w("title: Capability registry (kb_v2)\n")
    w("category: capabilities\n")
    w("source: kb_v2 catalogue corpus (469 files, all status: verified)\n")
    w("status: draft\n")
    w("last_reviewed: 2026-10-30\n")
    w("---\n\n")
    w("# Capability registry\n\n")
    w("Built from `kb_v2/` on 2026-10-30 by `chatbot/tools/build_registry_v2.py` "
      "(`chatbot/tools/extract_capabilities.py` does the page parsing, "
      "`chatbot/tools/accepted_vocabulary.txt` is the reviewed value queue). "
      "It replaces the draft that was extracted from the six v1 catalogue files.\n\n")
    n_vocab = sum(len(values[f][s]) for f in fam_order for s in values[f])
    n_site = sum(1 for r in rows if r["basis"] == "site-category")
    w(f"Rows: {len(rows)} supported offerings (one per product page that publishes a quote form; "
      f"{n_site} of them placed in a family by the site's own category listing), "
      f"{n_vocab} vocabulary value-slot pairs, {len(EXCLUDED)} exclusions, {len(GAUGES)} gauge rows, "
      f"{len(NOT_ATTESTED) + len(absent)} not-attested values.\n\n")
    w("## How to read a row\n\n")
    w("- `scope: page` means one product page names these values on one page. The page does not always "
      "state them together in one sentence, so a page row is evidence we can *discuss* the combination, "
      "not proof we ship it. `scope: family` is used only where the site states a family-level rule.\n")
    w("- `approved: pending` on every row means Sales has not signed it. Until signed, the loader classifies "
      "the tuple as `unknown_capability`: discuss, never assert.\n")
    w("- `source` paths are relative to the project root and point into `kb_v2/`, which is read-only here.\n")
    w("- spelling variants seen on the site (Softouch, soft-touch, GrayBoard, greyboard, buxboard, Bux Board, "
      "SpotUV) are folded to one cell by the builder's MERGE table and re-folded at query time by "
      "`bot/capability.py::normalise`.\n")
    w("- gauge figures live in their own table because `pt`, `mil`, `micron`, `oz`, `lb`, `gsm` and `mm` "
      "measure different things per family and the corpus only states them in FAQ prose. Fill weights "
      "(\"1 oz\", \"32 oz\"), corner radii, type sizes in pt and tent-leg ballast are **not** gauges; the "
      "inventory that produced this table rejected them.\n\n")

    w("## Vocabulary\n\n")
    w("Slots: `material`, `colour`, `finish`, `extras`, `insert`, `fold`. Colour stays out of the capability "
      "tuple even though the site prints it under `## Materials` - \"white\", \"silver\" and \"clear\" name an "
      "appearance, not a stock, and folding them into `material` would let \"clear bag\" and \"clear film\" "
      "mean the same thing.\n\n")
    w("```capability\n")
    w("# table: vocabulary\n")
    w("# family|slot|values\n")
    for family in fam_order:
        for slot in ("style", "material", "colour", "finish", "extras", "insert", "fold"):
            if slot == "style":
                seen: Counter = Counter()
                for row in per_family[family]:
                    seen[row["style"]] += 1
                vals = sorted(seen)
            else:
                vals = sorted(set(values[family][slot]))
            if not vals:
                continue
            w(f"{family}|{slot}|{cell(vals)}\n")
    w("```\n\n")

    w("## Supported offerings\n\n")
    w("One row per product page that publishes a quote form (a deal page and a category page are not "
      "offerings, so they contribute vocabulary but no row). The style cell is the page's own title.\n\n")
    w("```capability\n")
    w("# table: supported\n")
    w("# family|style|material|insert|finish|extras|gauge|scope|source|approved|note\n")
    for family in fam_order:
        for row in sorted(per_family[family], key=lambda r: r["style"].lower()):
            slots = row["slots"]
            rel = row["page"]["path"].relative_to(ROOT).as_posix()
            note = ("family taken from the site's own category listing"
                    if row["basis"] == "site-category"
                    else "family inferred from the page title, not from a category listing")
            w("|".join([
                family, row["style"], cell(slots.get("material", [])), cell(slots.get("insert", [])),
                cell(slots.get("finish", [])), cell(slots.get("extras", [])), "-", "page", rel,
                "pending", note,
            ]) + "\n")
    w("```\n\n")

    w("## Excluded\n\n")
    w("Only statements where print247 itself rules something out. The corpus is affirmative marketing copy: "
      "the crawler-recorded `## Not stated on page` bullets, the 31 \"no specification is available\" lines "
      "and every \"avoid this in your artwork\" instruction are absence or advice, not refusal, and none of "
      "them are here.\n\n")
    w("Every row is `kind: rule`, never `pair`. kb_v2 states a refusal as a use case (\"not for wet use\", "
      "\"not for heavy shipping\", \"not re-usable\"), and a use case is not one of the five tuple slots. "
      "A `pair` row would make the guard refuse a combination the site actually sells - rigid-cardboard "
      "display boxes with a window are on sale, the page only warns against shipping heavy goods in them. "
      "So the mechanical matcher stays unused until Sales attests a refusal that is really about the "
      "combination. Default-deny already prevents asserting any of these.\n\n")
    w("```capability\n")
    w("# table: excluded\n")
    w("# family|kind|style|material|insert|finish|extras|reason|source|approved\n")
    for row in EXCLUDED:
        w("|".join(row) + "\n")
    w("```\n\n")

    w("## Sizes\n\n")
    w("The plan's sizing rule is two sources only: a catalogue row or a visitor-typed number. kb_v2 makes "
      "that rule almost everything - one family publishes a numeric size list.\n\n")
    w("```capability\n")
    w("# table: sizes\n")
    w("# family|values|note|source\n")
    for row in SIZES:
        w("|".join(row) + "\n")
    w("```\n\n")

    w("## Gauges\n\n")
    w("`basis` says how much weight the figure carries: `page` is a spec bullet, `faq` is a Q&A answer on a "
      "product page, `knowledge` is a hub article that never claims the figure is ours to quote.\n\n")
    w("```capability\n")
    w("# table: gauges\n")
    w("# family|material|gauge|basis|source|note\n")
    for row in GAUGES:
        w("|".join(row) + "\n")
    w("```\n\n")

    w("## Questions for production\n\n")
    w("```capability\n")
    w("# table: needs_production\n")
    w("# family|question|asked|source\n")
    for row in NEEDS_PRODUCTION:
        w("|".join(row) + "\n")
    w("```\n\n")

    w("## Not attested\n\n")
    w("Values that must not appear in an answer as something we make. `class: probe` rows are the negative "
      "probes the bot must fail; `class: v1-absent` rows are what the old six-page vocabulary claimed and "
      "kb_v2 never says - they are kept for the auditor, and the primer lists only the probes, because 80 "
      "absent values in the prompt would push the useful ones out.\n\n")
    w("```capability\n")
    w("# table: not_attested\n")
    w("# family|value|note|class\n")
    for row in list(NOT_ATTESTED) + absent:
        w("|".join(row) + "\n")
    w("```\n\n")

    w("## Aliases\n\n")
    w("The written forms the site uses for one value, so a visitor's spelling resolves instead of reading "
      "as an invented noun. `bot/capability.py::normalise` folds a query through this table before it "
      "builds a tuple key; the builder folds the same pairs at extraction time via MERGE, so the two never "
      "drift apart.\n\n")
    w("```capability\n")
    w("# table: aliases\n")
    w("# variant|canonical\n")
    for variant, target in sorted(MERGE.items()):
        if variant != _norm(target):
            w(f"{variant}|{target}\n")
    w("```\n\n")

    w("## Catalogue pages with no family\n\n")
    w("```capability\n")
    w("# table: unmapped\n")
    w("# page|title|kind\n")
    for stem, title, kind in unmapped:
        w(f"{stem}|{extract.clean(title)}|{kind}\n")
    w("```\n")


V1_SNAPSHOT = Path(__file__).resolve().parent / "v1_vocabulary_snapshot.txt"


def missing_from_corpus() -> list[tuple[str, str, str, str]]:
    """v1 vocabulary values that kb_v2 never uses anywhere - honest absences, not refusals.

    Reads the pinned v1 snapshot, not the live registry: this generator is about to overwrite that file.
    """
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore").lower()
                     for part in ("catalog", "knowledge", "site")
                     for p in (extract.CORPUS / part).rglob("*.md"))
    flat = re.sub(r"[^a-z0-9 ]", " ", text)
    out: list[tuple[str, str]] = []
    for line in V1_SNAPSHOT.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("|")
        if len(parts) != 3:
            raise SystemExit(f"v1 snapshot line is not family|slot|values: {line[:60]}")
        family, slot, values_cell = parts
        if slot in {"free_params", "form_selectable", "style_card", "style", "gauge"}:
            continue
        for value in (v.strip() for v in values_cell.split(";")):
            if not value or value == "-":
                continue
            needle = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", value.lower())).strip()
            if f" {needle} " not in f" {flat} ":
                out.append((family, value, f"v1 vocabulary ({family}/{slot}); the string does not "
                                           f"occur anywhere in kb_v2", "v1-absent"))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
