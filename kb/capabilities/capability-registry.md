---
id: capability-registry
title: Capability registry (kb_v2)
category: capabilities
source: kb_v2 catalogue corpus (469 files, all status: verified)
status: draft
last_reviewed: 2026-10-30
---

# Capability registry

Built from `kb_v2/` on 2026-10-30 by `chatbot/tools/build_registry_v2.py` (`chatbot/tools/extract_capabilities.py` does the page parsing, `chatbot/tools/accepted_vocabulary.txt` is the reviewed value queue). It replaces the draft that was extracted from the six v1 catalogue files.

Rows: 147 supported offerings (one per product page that publishes a quote form; 87 of them placed in a family by the site's own category listing), 242 vocabulary value-slot pairs, 26 exclusions, 29 gauge rows, 56 not-attested values.

## How to read a row

- `scope: page` means one product page names these values on one page. The page does not always state them together in one sentence, so a page row is evidence we can *discuss* the combination, not proof we ship it. `scope: family` is used only where the site states a family-level rule.
- `approved: pending` on every row means Sales has not signed it. Until signed, the loader classifies the tuple as `unknown_capability`: discuss, never assert.
- `source` paths are relative to the project root and point into `kb_v2/`, which is read-only here.
- spelling variants seen on the site (Softouch, soft-touch, GrayBoard, greyboard, buxboard, Bux Board, SpotUV) are folded to one cell by the builder's MERGE table and re-folded at query time by `bot/capability.py::normalise`.
- gauge figures live in their own table because `pt`, `mil`, `micron`, `oz`, `lb`, `gsm` and `mm` measure different things per family and the corpus only states them in FAQ prose. Fill weights ("1 oz", "32 oz"), corner radii, type sizes in pt and tent-leg ballast are **not** gauges; the inventory that produced this table rejected them.

## Vocabulary

Slots: `material`, `colour`, `finish`, `extras`, `insert`, `fold`. Colour stays out of the capability tuple even though the site prints it under `## Materials` - "white", "silver" and "clear" name an appearance, not a stock, and folding them into `material` would let "clear bag" and "clear film" mean the same thing.

```capability
# table: vocabulary
# family|slot|values
boxes|style|Boxes With Lid; CBD Boxes; CBD Cream Boxes; Christmas Gift Boxes; Cigar Boxes; Comic Book Boxes; Cookie Boxes; Cupcake Boxes; Dietary Supplement packaging; Display Box With Logo; Double Tea Box with Magnetic Closure; Eyelash Boxes; Foundation Boxes; Gold Foil Boxes; Hemp Boxes; Holographic Foiling Boxes; Hoodie Packaging; Lip Balm Boxes; Luxury Clothing Packaging; Mailer Boxes; Match Boxes; Medical Box with insert; Medicine Boxes; Metalized Boxes; Muffin Boxes; PR Boxes; Perfume Boxes; Pharmaceutical Patch Box; Pie Boxes; Pop Counter Display Tray; Product Display Box; Rack display boxes; Shape Boxes; Sock Packaging Boxes; Standard Green Tea Boxes; Tea Bag Dispenser; Tea Tray and Lid Gift Boxes; Textured Boxes; Torch Boxes; Tuck Boxes; Underwear Packaging; Wallet Boxes
boxes|material|PET; PVC; SBS paperboard; acetate; b c flute; b flute; bux board; c flute; cardboard; cardstock; corrugated board; corrugated cardboard; double coated card stock; e b flute; e-flute; foil; grayboard; holographic cardboard; kraft; kraft board; kraft paperboard; paperboard; recycled paperboard; rigid board; rigid cardboard; silver cardboard; textured paper; white cardboard
boxes|colour|clear; silver; transparent; white
boxes|finish|3D raised UV; UV coating; aqueous coating; debossing; deep embossing; die cut; drip off; embossing; foil printing; foil stamping; gloss; gloss UV; gloss lamination; holographic; holographic foil; holographic foil printing; hot foil stamping; inside printing; lamination; matte; matte UV; matte lamination; soft touch; soft touch lamination; spot UV; spot foiling; spot gloss; textured; varnish
boxes|extras|LED light module; cut-out; handle; layered reveal mechanism; lift tab; magnetic closure; raised ink; resealable tab; ribbon pull; stackable design; vent hole; window
boxes|insert|foam insert; molded pulp tray; paperboard divider; sauce cup insert; velvet-lined tray
bags|style|3 Side Seal Pouches; Biodegradable StandUp Pouch; CBD Mylar Bags; Child-Resistant Pouches; Chocolate Mylar Bags; Christmas Gift Bags; Coffee Bags; Eco-Friendly Pouches; Flat Bottom Pouches; Hemp Flower Mylar Bag; Inside Printed Pouches; Mylar Bags; Plastics Bags; Poly Mailers; Pouches; Pre Roll Mylar Bags; Smell proof weed bags; Stand Up Pouches; Vape Cartridge Pouches; Vape Pouches; Weed Mylar Bags
bags|material|BOPP; PE; PET; PP; foil; foil pouch; kraft; metalized; mylar
bags|colour|clear; plain white; white
bags|finish|drip off; foil printing; gloss; holographic foil printing; inside printing; lamination; matte; soft touch; spot UV; spot foiling; spot matte; tactile feel
bags|extras|child-resistant zipper; easy-open zipper; euro hole; hang hole; tear notch; window; zipper
labels|style|Address Labels; Barcode Labels; Bottle Labels; Canning Labels; Clings; Cosmetic Labels; Cut-to-size Sticker Singles; Die Cut Labels; Domed 3D Labels; Domed 3D Stickers; Food Labels; Front-Adhesive Stickers; Heart Stickers; Hexagon Stickers; Holographic Labels; Holographic Stickers; Label Stickers; Metallic Labels; Name Labels; Political Bumper Stickers; Political Stickers; Product Labels; Round Labels; Shape Labels; Sheet Labels; Shipping Labels; Vinyl Labels; Vinyl Stickers; Water Bottle Stickers
labels|material|ABS; BOPP; PLA; clear film; foil; kraft; metallized film; nylon; polyester; static cling; vinyl
labels|colour|clear; iridescent; silver; white
labels|finish|3D raised UV; UV coating; anti-scratch lamination; aqueous coating; debossing; die cut; drip off; embossing; foil printing; foil stamping; gloss; gloss UV; gloss lamination; holographic; holographic foil printing; hot foil stamping; lamination; matte; matte UV; matte lamination; satin; soft touch; soft touch lamination; spot UV; spot foiling; spot gloss
labels|extras|colour customization; full bleed; no border; white border; window
labels|insert|tamper-evident seal
business_cards|style|3D Pop-up Folding Business Cards With Character; Business Card with QR Code; Embossed Gloss Business Cards; Foil Accent Business Cards; Folded Business Cards; Glossy Business Cards; Kraft Business Cards; Linen Business Cards; Matte Business Cards; NFC Business Cards; Painted Edge Business Cards; Political Business Cards; Round Corner Business Card; Standard Business Cards; Ultra Thick Business Cards
business_cards|material|PET; PVC; acrylic; cardstock; foil; grayboard; holographic cardboard; kraft; kraft board; silver cardboard; white cardboard
business_cards|finish|3D raised UV; debossing; deep embossing; drip off; embossing; gloss UV; gloss lamination; hot foil stamping; matte; matte lamination; soft touch lamination; spot UV; spot foiling; spot gloss; spot matte; tactile feel; varnish
business_cards|extras|window
business_cards|fold|half fold
banners|style|A-Frames; Angled Flags Banners; Banners Stands; Canopy Tents; Car Door Decals; Car Window Decals; Desk Name Plates; Metal Signs; Parking Sign; Pop Up Display; Pull up Banners; Rectangle Flags; Restroom Signs; Signicades; Step and Repeat Banners; Stretch Table Covers; Table Cloths; Table Runners; Tabletop signs; Vinyl Banner; Wall decals; Way Finding Sign; Window Decals
banners|material|corrugated plastic; foamcore; paperboard; polyester; static cling; vinyl
banners|colour|clear; frosted; metallic chrome; silver; white; white opaque
banners|finish|die cut; gloss; gloss lamination; grommets; holographic; hot foil stamping; kiss cut; matte; pole pockets; reinforced corners; reverse printing; varnish
banners|extras|perforation
print|style|Booklets; Bookmarks; Brochure Printing; Door hangers; Envelopes; Flyers; Greeting Cards; Invitations; Magnets; Numbered Tickets; Political Brochures; Political Postcards; Posters; Tear Cards; Variable Printing; Wall Calendars
print|material|cardstock; gloss paper; holographic cardboard; rigid cardboard; silver cardboard; white cardboard
print|colour|silver; white
print|finish|3D raised UV; aqueous coating; die cut; drip off; gloss; gloss lamination; holographic; lamination; matte; matte lamination; satin; soft touch; soft touch lamination; spot UV; spot foiling; spot gloss; textured; varnish
print|extras|perforation
print|fold|bi fold; envelope; insert and folder; tri fold
```

## Supported offerings

One row per product page that publishes a quote form (a deal page and a category page are not offerings, so they contribute vocabulary but no row). The style cell is the page's own title.

```capability
# table: supported
# family|style|material|insert|finish|extras|gauge|scope|source|approved|note
boxes|Boxes With Lid|white cardboard|-|-|-|-|page|kb_v2/catalog/catalog-custom-boxes-with-lid.md|pending|family inferred from the page title, not from a category listing
boxes|CBD Boxes|white cardboard|-|gloss lamination; matte lamination; soft touch; lamination; spot UV; foil printing; holographic foil printing; UV coating|-|-|page|kb_v2/catalog/catalog-cbd-boxes.md|pending|family taken from the site's own category listing
boxes|CBD Cream Boxes|paperboard; corrugated cardboard; grayboard; rigid board; bux board; rigid cardboard|-|gloss; matte; soft touch; lamination; spot UV; foil printing; holographic foil printing|-|-|page|kb_v2/catalog/catalog-cbd-cream-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Christmas Gift Boxes|white cardboard; silver cardboard; holographic cardboard; rigid cardboard|-|embossing; deep embossing; 3D raised UV; UV coating; hot foil stamping; debossing; inside printing; die cut|LED light module; lift tab|-|page|kb_v2/catalog/catalog-christmas-gift-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Cigar Boxes|rigid cardboard|-|spot gloss; drip off; soft touch lamination; matte; gloss; soft touch; lamination; spot UV; hot foil stamping; holographic foil; 3D raised UV; embossing; debossing|-|-|page|kb_v2/catalog/catalog-cigar-packaging.md|pending|family taken from the site's own category listing
boxes|Comic Book Boxes|grayboard; rigid board; white cardboard; holographic cardboard; cardboard; e-flute; b flute; c flute; e b flute; b c flute; kraft|-|-|-|-|page|kb_v2/catalog/catalog-comic-book-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Cookie Boxes|white cardboard|-|matte lamination; gloss lamination|-|-|page|kb_v2/catalog/catalog-cookie-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Cupcake Boxes|white cardboard|-|gloss lamination; matte lamination; matte; gloss; soft touch; drip off; lamination; spot UV; hot foil stamping; holographic foil; 3D raised UV; embossing; debossing|-|-|page|kb_v2/catalog/catalog-cupcake-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Dietary Supplement packaging|white cardboard|-|drip off; soft touch lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-dietary-supplement-packaging.md|pending|family taken from the site's own category listing
boxes|Display Box With Logo|rigid cardboard; white cardboard; holographic cardboard; silver cardboard; foil|-|gloss UV; gloss lamination; drip off; matte UV; spot gloss; soft touch lamination; matte lamination; deep embossing; hot foil stamping; inside printing; embossing; 3D raised UV; debossing|window|-|page|kb_v2/catalog/catalog-display-box-with-logo.md|pending|family inferred from the page title, not from a category listing
boxes|Double Tea Box with Magnetic Closure|holographic cardboard|-|gloss lamination; matte lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-double-tea-box-with-magnetic-closure.md|pending|family taken from the site's own category listing
boxes|Eyelash Boxes|rigid cardboard|-|gloss lamination; spot gloss; drip off|-|-|page|kb_v2/catalog/catalog-eyelash-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Foundation Boxes|rigid cardboard|-|gloss lamination; drip off; matte lamination|-|-|page|kb_v2/catalog/catalog-foundation-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Gold Foil Boxes|rigid cardboard; white cardboard; foil|-|holographic; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; embossing; deep embossing; 3D raised UV; inside printing; hot foil stamping; debossing|window|-|page|kb_v2/catalog/catalog-gold-foil-boxes.md|pending|family taken from the site's own category listing
boxes|Hemp Boxes|rigid cardboard; white cardboard; foil|-|holographic; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; embossing; deep embossing; 3D raised UV; inside printing; hot foil stamping; debossing|window|-|page|kb_v2/catalog/catalog-hemp-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Holographic Foiling Boxes|rigid cardboard; white cardboard; foil|-|holographic; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; embossing; deep embossing; 3D raised UV; inside printing; hot foil stamping; debossing|window|-|page|kb_v2/catalog/catalog-holographic-foiling-boxes.md|pending|family taken from the site's own category listing
boxes|Hoodie Packaging|e-flute; bux board; grayboard; cardstock; kraft; holographic cardboard|-|matte UV; spot gloss; drip off; gloss lamination|-|-|page|kb_v2/catalog/catalog-custom-hoodie-packaging.md|pending|family taken from the site's own category listing
boxes|Lip Balm Boxes|holographic cardboard|-|drip off; gloss lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-lip-balm-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Luxury Clothing Packaging|rigid cardboard; SBS paperboard; white cardboard; kraft; cardboard; corrugated board; silver cardboard; holographic cardboard; foil|-|matte lamination; soft touch lamination; spot gloss; drip off; gloss lamination; matte UV; embossing; deep embossing; debossing; hot foil stamping; 3D raised UV|-|-|page|kb_v2/catalog/catalog-luxury-clothing-packaging.md|pending|family taken from the site's own category listing
boxes|Mailer Boxes|kraft|-|matte lamination; drip off; spot gloss|-|-|page|kb_v2/catalog/catalog-mailer-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Match Boxes|rigid cardboard|-|-|-|-|page|kb_v2/catalog/catalog-custom-match-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Medical Box with insert|holographic cardboard|-|spot gloss; drip off; soft touch lamination|-|-|page|kb_v2/catalog/catalog-custom-medical-box-with-insert.md|pending|family taken from the site's own category listing
boxes|Medicine Boxes|SBS paperboard; kraft; recycled paperboard; corrugated board; rigid board; white cardboard|-|-|-|-|page|kb_v2/catalog/catalog-medicine-boxes.md|pending|family taken from the site's own category listing
boxes|Metalized Boxes|holographic cardboard|-|matte UV; drip off; spot gloss|-|-|page|kb_v2/catalog/catalog-metalized-boxes.md|pending|family taken from the site's own category listing
boxes|Muffin Boxes|rigid board; white cardboard|-|gloss lamination; matte lamination|-|-|page|kb_v2/catalog/catalog-muffin-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Perfume Boxes|rigid cardboard; white cardboard; foil|-|holographic; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; gloss; matte; UV coating; spot UV; varnish; foil stamping; embossing; deep embossing; 3D raised UV; inside printing; hot foil stamping; debossing|window|-|page|kb_v2/catalog/catalog-perfume-boxes.md|pending|family taken from the site's own category listing
boxes|Pharmaceutical Patch Box|white cardboard|-|-|-|-|page|kb_v2/catalog/catalog-pharmaceutical-patch-box.md|pending|family inferred from the page title, not from a category listing
boxes|Pie Boxes|white cardboard|-|matte lamination; gloss lamination|-|-|page|kb_v2/catalog/catalog-pie-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Pop Counter Display Tray|rigid cardboard|-|-|-|-|page|kb_v2/catalog/catalog-pop-counter-display-tray.md|pending|family taken from the site's own category listing
boxes|PR Boxes|double coated card stock; kraft; e-flute; rigid board; PVC|-|gloss; matte; soft touch; drip off; lamination; aqueous coating; spot UV; hot foil stamping; 3D raised UV; embossing; debossing; textured|window; cut-out; handle|-|page|kb_v2/catalog/catalog-pr-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Product Display Box|silver cardboard|-|spot gloss; gloss UV; matte UV; gloss lamination|-|-|page|kb_v2/catalog/catalog-custom-product-display-box.md|pending|family taken from the site's own category listing
boxes|Rack display boxes|corrugated cardboard; bux board; grayboard; kraft; cardstock; holographic cardboard|-|spot gloss; gloss lamination; matte lamination; soft touch; lamination; gloss; matte; spot UV; varnish; foil printing; holographic; hot foil stamping|-|-|page|kb_v2/catalog/catalog-rack-display-boxes.md|pending|family taken from the site's own category listing
boxes|Shape Boxes|white cardboard; silver cardboard; holographic cardboard; rigid cardboard; foil|-|drip off; gloss lamination; matte lamination; soft touch lamination; spot gloss; embossing; deep embossing; 3D raised UV; inside printing; hot foil stamping; debossing|window|-|page|kb_v2/catalog/catalog-custom-shaped-boxes.md|pending|family taken from the site's own category listing
boxes|Sock Packaging Boxes|holographic cardboard|-|matte UV; drip off; spot gloss|-|-|page|kb_v2/catalog/catalog-sock-packaging-box.md|pending|family taken from the site's own category listing
boxes|Standard Green Tea Boxes|holographic cardboard|-|gloss lamination; matte lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-standard-green-tea-boxes.md|pending|family taken from the site's own category listing
boxes|Tea Bag Dispenser|rigid cardboard; silver cardboard; foil|-|holographic; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; embossing; deep embossing; 3D raised UV; inside printing; hot foil stamping; debossing|window|-|page|kb_v2/catalog/catalog-tea-bag-dispenser.md|pending|family taken from the site's own category listing
boxes|Tea Tray and Lid Gift Boxes|-|-|gloss lamination; matte lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-tea-tray-and-lid-gift-boxes.md|pending|family taken from the site's own category listing
boxes|Textured Boxes|bux board; kraft; rigid cardboard; textured paper; white cardboard|-|soft touch lamination; spot gloss; drip off; debossing; embossing; gloss; matte; soft touch; lamination; spot UV; foil printing; holographic; spot foiling|raised ink|-|page|kb_v2/catalog/catalog-textured-boxes.md|pending|family taken from the site's own category listing
boxes|Torch Boxes|cardboard; paperboard; corrugated cardboard; kraft; rigid cardboard|-|holographic; spot foiling; gloss; matte; soft touch; lamination; spot UV; foil printing|-|-|page|kb_v2/catalog/catalog-torch-boxes.md|pending|family taken from the site's own category listing
boxes|Tuck Boxes|double coated card stock; kraft; corrugated board; bux board; kraft board; white cardboard|-|-|-|-|page|kb_v2/catalog/catalog-tuck-boxes.md|pending|family inferred from the page title, not from a category listing
boxes|Underwear Packaging|silver cardboard|-|drip off; spot gloss; soft touch lamination|-|-|page|kb_v2/catalog/catalog-underwear-packaging.md|pending|family inferred from the page title, not from a category listing
boxes|Wallet Boxes|silver cardboard|-|drip off; gloss lamination; spot gloss; matte; gloss; soft touch; lamination; spot UV; hot foil stamping; holographic foil; 3D raised UV; embossing; debossing|-|-|page|kb_v2/catalog/catalog-wallet-boxes.md|pending|family taken from the site's own category listing
bags|3 Side Seal Pouches|-|-|spot UV; soft touch; matte; inside printing|-|-|page|kb_v2/catalog/catalog-3-side-seal-pouches.md|pending|family inferred from the page title, not from a category listing
bags|Biodegradable StandUp Pouch|-|-|soft touch; inside printing; spot UV; matte|-|-|page|kb_v2/catalog/catalog-biodegradable-standup-pouch.md|pending|family inferred from the page title, not from a category listing
bags|CBD Mylar Bags|metalized|-|drip off; matte; soft touch; spot UV; inside printing; gloss; spot foiling; spot matte; tactile feel|window|-|page|kb_v2/catalog/catalog-cbd-mylar-bag.md|pending|family inferred from the page title, not from a category listing
bags|Child-Resistant Pouches|metalized|-|spot UV; soft touch; matte; inside printing|-|-|page|kb_v2/catalog/catalog-child-resistant-pouches.md|pending|family inferred from the page title, not from a category listing
bags|Chocolate Mylar Bags|kraft|-|gloss; inside printing; spot UV; matte|-|-|page|kb_v2/catalog/catalog-chocolate-mylar-bag.md|pending|family inferred from the page title, not from a category listing
bags|Christmas Gift Bags|mylar|-|-|zipper|-|page|kb_v2/catalog/catalog-christmas-gift-bags.md|pending|family inferred from the page title, not from a category listing
bags|Coffee Bags|kraft|-|spot UV; matte; soft touch; inside printing|-|-|page|kb_v2/catalog/catalog-coffee-bags.md|pending|family inferred from the page title, not from a category listing
bags|Eco-Friendly Pouches|kraft|-|drip off; gloss; matte; soft touch; spot UV; inside printing; spot foiling; spot matte; tactile feel|window|-|page|kb_v2/catalog/catalog-eco-friendly-pouches.md|pending|family inferred from the page title, not from a category listing
bags|Flat Bottom Pouches|-|-|drip off; gloss; matte; spot UV; inside printing; spot foiling; spot matte; tactile feel|window|-|page|kb_v2/catalog/catalog-flat-bottom-pouches.md|pending|family inferred from the page title, not from a category listing
bags|Hemp Flower Mylar Bag|metalized|-|drip off; gloss; matte; soft touch; spot UV; inside printing; spot foiling; spot matte; tactile feel|window|-|page|kb_v2/catalog/catalog-hemp-flower-mylar-bag.md|pending|family inferred from the page title, not from a category listing
bags|Inside Printed Pouches|kraft|-|gloss; inside printing; matte; soft touch|-|-|page|kb_v2/catalog/catalog-inside-printed-pouches.md|pending|family inferred from the page title, not from a category listing
bags|Mylar Bags|PE; PP; PET; foil; kraft; metalized|-|gloss; spot UV; matte; soft touch|-|-|page|kb_v2/catalog/catalog-custom-mylar-bags.md|pending|family inferred from the page title, not from a category listing
bags|Plastics Bags|-|-|-|-|-|page|kb_v2/catalog/catalog-plastics.md|pending|family inferred from the page title, not from a category listing
bags|Poly Mailers|metalized; foil pouch; kraft; PE; PP; PET; foil|-|drip off; gloss; matte; soft touch; spot UV; inside printing; spot foiling; spot matte; tactile feel|window|-|page|kb_v2/catalog/catalog-poly-mailers.md|pending|family inferred from the page title, not from a category listing
bags|Pouches|kraft; PET; BOPP; foil; metalized; foil pouch|-|inside printing; gloss; soft touch; matte|-|-|page|kb_v2/catalog/catalog-custom-pouches.md|pending|family taken from the site's own category listing
bags|Pre Roll Mylar Bags|-|-|gloss; spot UV; inside printing; matte|-|-|page|kb_v2/catalog/catalog-pre-roll-mylar-bags.md|pending|family inferred from the page title, not from a category listing
bags|Smell proof weed bags|PE; PP; PET; foil; kraft; metalized|-|gloss; matte; inside printing; soft touch|-|-|page|kb_v2/catalog/catalog-custom-smell-proof-weed-bags.md|pending|family inferred from the page title, not from a category listing
bags|Stand Up Pouches|PE; PP; PET; foil; kraft; metalized|-|gloss; soft touch; matte; inside printing; lamination; spot UV; foil printing; holographic foil printing|tear notch; hang hole; euro hole; easy-open zipper; child-resistant zipper|-|page|kb_v2/catalog/catalog-stand-up-pouch.md|pending|family inferred from the page title, not from a category listing
bags|Vape Cartridge Pouches|-|-|inside printing; soft touch; gloss; matte|-|-|page|kb_v2/catalog/catalog-custom-vape-cartridge-pouches.md|pending|family inferred from the page title, not from a category listing
bags|Vape Pouches|-|-|inside printing; gloss; soft touch; matte|-|-|page|kb_v2/catalog/catalog-vape-pouches.md|pending|family inferred from the page title, not from a category listing
bags|Weed Mylar Bags|foil pouch|-|drip off; matte; soft touch; spot UV; inside printing; gloss; spot foiling; spot matte; tactile feel|window|-|page|kb_v2/catalog/catalog-weed-mylar-bags.md|pending|family inferred from the page title, not from a category listing
labels|Address Labels|vinyl|-|holographic; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; gloss; 3D raised UV; spot foiling; lamination; hot foil stamping; aqueous coating|-|-|page|kb_v2/catalog/catalog-address-labels.md|pending|family taken from the site's own category listing
labels|Barcode Labels|vinyl|-|holographic; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; die cut; 3D raised UV; spot foiling|-|-|page|kb_v2/catalog/catalog-barcode-labels.md|pending|family taken from the site's own category listing
labels|Bottle Labels|PLA; ABS; nylon|-|gloss; spot gloss; gloss lamination; drip off; soft touch lamination; gloss UV; matte UV; aqueous coating|-|-|page|kb_v2/catalog/catalog-bottle-labels.md|pending|family taken from the site's own category listing
labels|Canning Labels|-|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; 3D raised UV; spot foiling|-|-|page|kb_v2/catalog/catalog-canning-labels.md|pending|family inferred from the page title, not from a category listing
labels|Clings|-|-|-|-|-|page|kb_v2/catalog/catalog-clings.md|pending|family inferred from the page title, not from a category listing
labels|Cosmetic Labels|-|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; gloss; 3D raised UV; spot foiling; aqueous coating|-|-|page|kb_v2/catalog/catalog-cosmetic-labels.md|pending|family inferred from the page title, not from a category listing
labels|Cut-to-size Sticker Singles|-|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; 3D raised UV; spot foiling|-|-|page|kb_v2/catalog/catalog-cut-to-size-singles.md|pending|family taken from the site's own category listing
labels|Die Cut Labels|vinyl|-|gloss; matte; soft touch; lamination; spot UV; foil printing; holographic foil printing; drip off; spot gloss; matte lamination|-|-|page|kb_v2/catalog/catalog-die-cut-labels.md|pending|family taken from the site's own category listing
labels|Domed 3D Labels|-|-|-|-|-|page|kb_v2/catalog/catalog-domed-3d-labels.md|pending|family taken from the site's own category listing
labels|Domed 3D Stickers|-|-|matte lamination; drip off; gloss lamination; gloss; matte; soft touch; lamination; spot UV; foil printing; holographic foil printing; UV coating|-|-|page|kb_v2/catalog/catalog-domed-3d-stickers.md|pending|family taken from the site's own category listing
labels|Food Labels|vinyl|-|holographic; spot gloss; gloss lamination; drip off; gloss; matte; soft touch lamination; spot foiling; 3D raised UV; die cut|-|-|page|kb_v2/catalog/catalog-food-labels.md|pending|family taken from the site's own category listing
labels|Front-Adhesive Stickers|vinyl; polyester; static cling|-|-|window|-|page|kb_v2/catalog/catalog-front-adhesive-stickers.md|pending|family taken from the site's own category listing
labels|Heart Stickers|vinyl|-|gloss; matte; soft touch; lamination; spot UV; foil printing; holographic foil printing|-|-|page|kb_v2/catalog/catalog-heart-stickers.md|pending|family taken from the site's own category listing
labels|Hexagon Stickers|vinyl|-|holographic; gloss lamination; drip off; soft touch; matte; spot gloss; 3D raised UV; spot foiling; matte lamination|-|-|page|kb_v2/catalog/catalog-hexagone-stickers.md|pending|family taken from the site's own category listing
labels|Holographic Labels|metallized film; BOPP; vinyl|tamper-evident seal|spot gloss; gloss lamination; gloss; lamination|colour customization|-|page|kb_v2/catalog/catalog-holographic-labels.md|pending|family taken from the site's own category listing
labels|Holographic Stickers|-|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; gloss; 3D raised UV; spot foiling; aqueous coating|-|-|page|kb_v2/catalog/catalog-holographic-stickers.md|pending|family taken from the site's own category listing
labels|Label Stickers|vinyl|-|holographic; gloss; matte; drip off; soft touch lamination; spot foiling; 3D raised UV; die cut|-|-|page|kb_v2/catalog/catalog-custom-labels.md|pending|family inferred from the page title, not from a category listing
labels|Metallic Labels|-|-|-|-|-|page|kb_v2/catalog/catalog-metallic-labels.md|pending|family taken from the site's own category listing
labels|Name Labels|vinyl|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; gloss; 3D raised UV; spot foiling|-|-|page|kb_v2/catalog/catalog-name-labels.md|pending|family taken from the site's own category listing
labels|Political Bumper Stickers|vinyl|-|holographic|-|-|page|kb_v2/catalog/catalog-custom-political-bumper-stickers.md|pending|family inferred from the page title, not from a category listing
labels|Political Stickers|-|-|-|-|-|page|kb_v2/catalog/catalog-custom-political-stickers.md|pending|family inferred from the page title, not from a category listing
labels|Product Labels|BOPP; vinyl; polyester; kraft; clear film; foil|-|gloss; matte; soft touch; UV coating; spot UV; spot gloss; drip off; matte lamination|-|-|page|kb_v2/catalog/catalog-product-labels.md|pending|family taken from the site's own category listing
labels|Round Labels|-|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; gloss; 3D raised UV; spot foiling; die cut|-|-|page|kb_v2/catalog/catalog-round-labels.md|pending|family taken from the site's own category listing
labels|Shape Labels|-|-|gloss; matte; soft touch; spot UV; foil stamping; embossing; debossing; satin; anti-scratch lamination|-|-|page|kb_v2/catalog/catalog-custom-shape-labels.md|pending|family taken from the site's own category listing
labels|Sheet Labels|metallized film; BOPP; vinyl|-|gloss lamination|-|-|page|kb_v2/catalog/catalog-sheet-labels.md|pending|family inferred from the page title, not from a category listing
labels|Shipping Labels|-|-|-|-|-|page|kb_v2/catalog/catalog-mailing-shipping-labels.md|pending|family taken from the site's own category listing
labels|Shipping Labels|-|-|gloss; soft touch lamination; gloss lamination|-|-|page|kb_v2/catalog/catalog-shipping-labels.md|pending|family taken from the site's own category listing
labels|Vinyl Labels|-|-|matte lamination; gloss lamination; gloss|-|-|page|kb_v2/catalog/catalog-vinyl-labels.md|pending|family taken from the site's own category listing
labels|Vinyl Stickers|vinyl|-|matte lamination; gloss lamination; matte UV; spot gloss; gloss UV; drip off; soft touch lamination; spot foiling; 3D raised UV|-|-|page|kb_v2/catalog/catalog-vinyl-stickers.md|pending|family taken from the site's own category listing
labels|Water Bottle Stickers|vinyl|-|holographic; drip off; gloss lamination; spot gloss; spot foiling; 3D raised UV|full bleed; white border; no border|-|page|kb_v2/catalog/catalog-water-bottle-stickers.md|pending|family inferred from the page title, not from a category listing
business_cards|3D Pop-up Folding Business Cards With Character|white cardboard|-|-|-|-|page|kb_v2/catalog/catalog-3d-pop-up-folding-business-cards-with-character.md|pending|family inferred from the page title, not from a category listing
business_cards|Business Card with QR Code|cardstock; kraft; PVC; PET; acrylic|-|drip off; matte lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-qr-code-business-cards.md|pending|family taken from the site's own category listing
business_cards|Embossed Gloss Business Cards|-|-|gloss UV; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; 3D raised UV; spot foiling; spot matte; tactile feel|window|-|page|kb_v2/catalog/catalog-embossed-gloss-business-cards.md|pending|family taken from the site's own category listing
business_cards|Foil Accent Business Cards|white cardboard; silver cardboard; holographic cardboard|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; matte; spot UV; 3D raised UV; spot foiling; spot matte; tactile feel|-|-|page|kb_v2/catalog/catalog-foil-accent-business-cards.md|pending|family taken from the site's own category listing
business_cards|Folded Business Cards|foil|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; embossing; deep embossing; 3D raised UV; hot foil stamping; debossing|window|-|page|kb_v2/catalog/catalog-folded-business-card.md|pending|family inferred from the page title, not from a category listing
business_cards|Glossy Business Cards|holographic cardboard|-|drip off; matte lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-glossy-business-cards.md|pending|family taken from the site's own category listing
business_cards|Kraft Business Cards|white cardboard|-|-|-|-|page|kb_v2/catalog/catalog-kraft-business-cards.md|pending|family taken from the site's own category listing
business_cards|Linen Business Cards|-|-|drip off; spot gloss; matte lamination|-|-|page|kb_v2/catalog/catalog-linen-business-cards.md|pending|family taken from the site's own category listing
business_cards|Matte Business Cards|white cardboard; silver cardboard; holographic cardboard|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; matte; spot UV; 3D raised UV; spot foiling; spot matte; tactile feel|-|-|page|kb_v2/catalog/catalog-matte-business-cards.md|pending|family taken from the site's own category listing
business_cards|NFC Business Cards|-|-|gloss lamination; matte lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-nfc-business-cards.md|pending|family taken from the site's own category listing
business_cards|Painted Edge Business Cards|-|-|matte lamination; drip off; gloss lamination|-|-|page|kb_v2/catalog/catalog-painted-edge-business-cards.md|pending|family taken from the site's own category listing
business_cards|Political Business Cards|cardstock|-|-|-|-|page|kb_v2/catalog/catalog-custom-political-business-cards.md|pending|family inferred from the page title, not from a category listing
business_cards|Round Corner Business Card|silver cardboard|-|spot gloss; gloss lamination; drip off|-|-|page|kb_v2/catalog/catalog-round-corner-business-card.md|pending|family taken from the site's own category listing
business_cards|Standard Business Cards|cardstock; kraft; PVC; PET; acrylic|-|gloss UV; gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; 3D raised UV; spot foiling; tactile feel; spot UV; varnish|-|-|page|kb_v2/catalog/catalog-standard-business-card.md|pending|family taken from the site's own category listing
business_cards|Ultra Thick Business Cards|grayboard; cardstock; kraft board; holographic cardboard|-|-|-|-|page|kb_v2/catalog/catalog-ultra-thick-business-cards.md|pending|family taken from the site's own category listing
banners|A-Frames|-|-|-|-|-|page|kb_v2/catalog/catalog-a-frames.md|pending|family taken from the site's own category listing
banners|Angled Flags Banners|-|-|-|-|-|page|kb_v2/catalog/catalog-angled-flags-banners.md|pending|family taken from the site's own category listing
banners|Banners Stands|-|-|-|-|-|page|kb_v2/catalog/catalog-banners-stands.md|pending|family taken from the site's own category listing
banners|Canopy Tents|-|-|-|-|-|page|kb_v2/catalog/catalog-canopy-tents.md|pending|family taken from the site's own category listing
banners|Car Door Decals|-|-|-|-|-|page|kb_v2/catalog/catalog-car-door-decals.md|pending|family taken from the site's own category listing
banners|Car Window Decals|vinyl|-|holographic; gloss; matte|-|-|page|kb_v2/catalog/catalog-car-window-decals.md|pending|family taken from the site's own category listing
banners|Desk Name Plates|-|-|-|-|-|page|kb_v2/catalog/catalog-desk-name-plates.md|pending|family taken from the site's own category listing
banners|Metal Signs|-|-|-|-|-|page|kb_v2/catalog/catalog-metal-signs.md|pending|family taken from the site's own category listing
banners|Parking Sign|-|-|-|-|-|page|kb_v2/catalog/catalog-parking-sign.md|pending|family taken from the site's own category listing
banners|Pop Up Display|-|-|-|-|-|page|kb_v2/catalog/catalog-pop-up-display.md|pending|family taken from the site's own category listing
banners|Pull up Banners|vinyl; polyester|-|-|-|-|page|kb_v2/catalog/catalog-pull-up-banners.md|pending|family taken from the site's own category listing
banners|Rectangle Flags|-|-|-|-|-|page|kb_v2/catalog/catalog-rectangle-flags.md|pending|family taken from the site's own category listing
banners|Restroom Signs|-|-|holographic; matte; gloss lamination|-|-|page|kb_v2/catalog/catalog-restroom-signs.md|pending|family taken from the site's own category listing
banners|Signicades|corrugated plastic|-|gloss lamination; matte|-|-|page|kb_v2/catalog/catalog-signicades.md|pending|family taken from the site's own category listing
banners|Step and Repeat Banners|-|-|-|-|-|page|kb_v2/catalog/catalog-step-and-repeat-banners.md|pending|family taken from the site's own category listing
banners|Stretch Table Covers|-|-|-|-|-|page|kb_v2/catalog/catalog-stretch-table-covers.md|pending|family taken from the site's own category listing
banners|Table Cloths|-|-|-|-|-|page|kb_v2/catalog/catalog-table-cloths.md|pending|family taken from the site's own category listing
banners|Table Runners|-|-|-|-|-|page|kb_v2/catalog/catalog-table-runners.md|pending|family taken from the site's own category listing
banners|Tabletop signs|corrugated plastic; foamcore; paperboard|-|varnish; hot foil stamping; gloss; matte|-|-|page|kb_v2/catalog/catalog-tabletop-signs.md|pending|family taken from the site's own category listing
banners|Vinyl Banner|-|-|grommets; pole pockets; reinforced corners|-|-|page|kb_v2/catalog/catalog-vinyl-banner.md|pending|family taken from the site's own category listing
banners|Wall decals|-|-|-|-|-|page|kb_v2/catalog/catalog-wall-decals.md|pending|family taken from the site's own category listing
banners|Way Finding Sign|-|-|holographic; gloss lamination; matte|-|-|page|kb_v2/catalog/catalog-way-finding-sign.md|pending|family taken from the site's own category listing
banners|Window Decals|vinyl; static cling|-|die cut; kiss cut; reverse printing|perforation|-|page|kb_v2/catalog/catalog-window-decals.md|pending|family taken from the site's own category listing
print|Booklets|-|-|soft touch; matte; gloss; textured; spot UV; varnish; satin; aqueous coating; holographic|-|-|page|kb_v2/catalog/catalog-booklets.md|pending|family taken from the site's own category listing
print|Bookmarks|white cardboard; silver cardboard; rigid cardboard|-|holographic; drip off; gloss; matte; soft touch lamination; spot gloss|-|-|page|kb_v2/catalog/catalog-bookmarks.md|pending|family taken from the site's own category listing
print|Brochure Printing|gloss paper|-|matte; gloss; soft touch; drip off; lamination; die cut|perforation|-|page|kb_v2/catalog/catalog-brochures.md|pending|family taken from the site's own category listing
print|Door hangers|-|-|gloss lamination; drip off; soft touch lamination; matte lamination; spot gloss; 3D raised UV; spot foiling|-|-|page|kb_v2/catalog/catalog-door-hanger.md|pending|family inferred from the page title, not from a category listing
print|Envelopes|-|-|-|-|-|page|kb_v2/catalog/catalog-envelope.md|pending|family inferred from the page title, not from a category listing
print|Flyers|-|-|-|-|-|page|kb_v2/catalog/catalog-flyers.md|pending|family inferred from the page title, not from a category listing
print|Greeting Cards|-|-|-|-|-|page|kb_v2/catalog/catalog-greeting-cards.md|pending|family taken from the site's own category listing
print|Invitations|-|-|-|-|-|page|kb_v2/catalog/catalog-invitations.md|pending|family taken from the site's own category listing
print|Magnets|-|-|-|-|-|page|kb_v2/catalog/catalog-magnets.md|pending|family taken from the site's own category listing
print|Numbered Tickets|-|-|-|-|-|page|kb_v2/catalog/catalog-numbered-tickets.md|pending|family inferred from the page title, not from a category listing
print|Political Brochures|gloss paper|-|matte; gloss; soft touch; drip off; lamination; die cut|perforation|-|page|kb_v2/catalog/catalog-custom-political-brochures.md|pending|family inferred from the page title, not from a category listing
print|Political Postcards|cardstock|-|-|-|-|page|kb_v2/catalog/catalog-custom-political-postcards.md|pending|family inferred from the page title, not from a category listing
print|Posters|-|-|-|-|-|page|kb_v2/catalog/catalog-poster-boards.md|pending|family inferred from the page title, not from a category listing
print|Tear Cards|holographic cardboard|-|-|-|-|page|kb_v2/catalog/catalog-custom-tear-cards.md|pending|family inferred from the page title, not from a category listing
print|Variable Printing|-|-|-|-|-|page|kb_v2/catalog/catalog-variable-printing.md|pending|family inferred from the page title, not from a category listing
print|Wall Calendars|-|-|-|-|-|page|kb_v2/catalog/catalog-wall-calenders.md|pending|family inferred from the page title, not from a category listing
```

## Excluded

Only statements where print247 itself rules something out. The corpus is affirmative marketing copy: the crawler-recorded `## Not stated on page` bullets, the 31 "no specification is available" lines and every "avoid this in your artwork" instruction are absence or advice, not refusal, and none of them are here.

Every row is `kind: rule`, never `pair`. kb_v2 states a refusal as a use case ("not for wet use", "not for heavy shipping", "not re-usable"), and a use case is not one of the five tuple slots. A `pair` row would make the guard refuse a combination the site actually sells - rigid-cardboard display boxes with a window are on sale, the page only warns against shipping heavy goods in them. So the mechanical matcher stays unused until Sales attests a refusal that is really about the combination. Default-deny already prevents asserting any of these.

```capability
# table: excluded
# family|kind|style|material|insert|finish|extras|reason|source|approved
labels|rule|clings|-|-|-|-|static cling will not hold on textured or porous walls; the electrostatic grip drops and the edge lifts|kb_v2/catalog/catalog-clings.md|pending
banners|rule|-|-|-|-|-|car-window clings must not sit in the driver's direct line of sight (safety, not capability)|kb_v2/catalog/catalog-clings.md|pending
labels|rule|-|-|-|-|-|front-adhesive decals are refused on textured or porous surfaces; the adhesive needs a clean flat surface|kb_v2/catalog/catalog-front-adhesive-stickers.md|pending
labels|rule|front-adhesive stickers|-|-|-|-|vinyl front-adhesive is one-time application; it loses its stick once removed, so reuse is not offered|kb_v2/catalog/catalog-front-adhesive-stickers.md|pending
labels|rule|window decals|-|-|-|reuse|sticky vinyl decals are for long-term application and are not re-usable; only static cling is|kb_v2/catalog/catalog-window-decals.md|pending
labels|rule|-|paper|-|-|-|paper stock labels are not made for water or weather; wet use needs a synthetic stock|kb_v2/catalog/catalog-cosmetic-labels.md|pending
labels|rule|specialty food labels|-|-|-|-|we will not print a food label on stock that cannot withstand cold storage, oil or handling|kb_v2/catalog/catalog-labels-stickers-specialty-labels.md|pending
boxes|rule|display boxes|rigid cardboard|-|window|-|open-front display boxes are shelf units and are not durable for heavy shipping|kb_v2/catalog/catalog-display-box-with-logo.md|pending
boxes|rule|-|paperboard|-|-|-|paperboard alone does not control temperature; coatings only block moisture|kb_v2/catalog/catalog-medicine-boxes.md|pending
boxes|rule|-|-|foam insert|-|-|precision foam inserts suit uneven bottles but the page warns they hurt the pack's recyclability|kb_v2/catalog/catalog-perfume-boxes.md|pending
business_cards|rule|-|-|-|foil stamping|-|foil runs under 1,000 are refused for machine set-up, not price: print 1,000 and split the batch|kb_v2/catalog/catalog-foil-accent-business-cards.md|pending
bags|rule|-|foil|-|-|-|foil-lined structures are multi-layer and some recycling streams reject them, so no curbside claim|kb_v2/catalog/catalog-child-resistant-pouches.md|pending
bags|rule|-|mylar|-|deep debossing|-|thin film cannot hold a deep debossed impression; the hub limits it to thicker bags|kb_v2/knowledge/know-mylar-bags-pouches-how-debossed-printing-works-on-mylar-packaging.md|pending
bags|rule|-|-|-|-|-|flexographic printing is refused for short runs and for designs that keep changing (plate cost)|kb_v2/knowledge/know-mylar-bags-pouches-when-to-use-flexographic-printing-for-packaging.md|pending
bags|rule|-|-|-|-|-|flexographic printing is not quoted for photo-level sharp detail|kb_v2/knowledge/know-mylar-bags-pouches-when-to-use-flexographic-printing-for-packaging.md|pending
bags|rule|-|-|-|-|press-to-close zipper|a press-to-close zipper is not sold as a replacement for the original heat-seal barrier|kb_v2/knowledge/know-mylar-bags-pouches-press-to-close-zipper-mylar-pouches.md|pending
bags|rule|-|-|-|-|-|a standard sealed pouch is unsuitable for products that keep releasing gas (coffee) unless a degassing valve is added|kb_v2/knowledge/know-mylar-bags-pouches-understanding-degassing-valves-in-mylar-bags.md|pending
bags|rule|-|-|-|-|-|not every vacuum pouch is heat-safe; the hub says to check the product specification|kb_v2/knowledge/know-mylar-bags-pouches-what-are-vacuum-pouches.md|pending
banners|rule|wall signs|-|-|-|-|the wrinkle-free fabric sign grade is explicitly not recommended for exterior UV and rain|kb_v2/knowledge/know-signs-and-banners-what-are-wall-signs-light-and-simple-guide-to-this-signage-in-everyday-life.md|pending
boxes|rule|pillow boxes|-|-|-|-|pillow boxes are described as carrying small, light goods only, not heavy items|kb_v2/knowledge/know-folding-cartons-pillow-boxes-when-minimalism-becomes-the-latest-trend.md|pending
boxes|rule|seal-end boxes|-|-|-|-|a seal-end box is not meant for products the customer opens and closes repeatedly|kb_v2/knowledge/know-folding-cartons-seal-end-box-packaging-a-brief-overview.md|pending
boxes|rule|-|duplex board|-|-|-|duplex board is ruled out for very heavy or delicate products|kb_v2/knowledge/know-folding-cartons-what-is-a-duplex-board-and-why-is-it-popular.md|pending
boxes|rule|-|CCNB|-|-|-|CCNB is not offered for heavy-duty use|kb_v2/knowledge/know-folding-cartons-clay-coated-news-back-ccnb-cost-effective-packaging.md|pending
boxes|rule|-|lined paperboard|-|-|-|lined paperboard is not supported for heavy products|kb_v2/knowledge/know-folding-cartons-what-is-lined-paperboard.md|pending
boxes|rule|-|chipboard|-|-|-|chipboard cannot take very heavy weight; it is a shape-and-structure stock|kb_v2/knowledge/know-folding-cartons-what-is-a-chipboard-and-what-role-does-it-play-in-packaging.md|pending
print|rule|-|construction paper|-|-|-|construction paper is ruled out for detailed printing; the surface is rough|kb_v2/knowledge/know-folding-cartons-what-is-construction-paper.md|pending
```

## Sizes

The plan's sizing rule is two sources only: a catalogue row or a visitor-typed number. kb_v2 makes that rule almost everything - one family publishes a numeric size list.

```capability
# table: sizes
# family|values|note|source
boxes|-|no size grid and no standard: pages answer "any size and any shape" or "custom sizes and measurements", so a box size comes from the visitor or from Sales; the only figures in the corpus are cake boxes up to 14 in and pie boxes 9-12 in|kb_v2/catalog/catalog-christmas-gift-boxes.md; kb_v2/catalog/catalog-category-food-beverage-boxes.md
bags|-|no size grid: the corpus names sizes in words (small, large, extra large) and lists fill capacities 1 oz to 32 oz under Materials on the stand-up pouch page, never as a size table, so a capacity figure is not a size and must not be quoted as one|kb_v2/catalog/catalog-christmas-gift-bags.md; kb_v2/catalog/catalog-stand-up-pouch.md
labels|-|no size grid: pages say "Standard & Custom Sizes", "Fully Custom (Any Shape & Size)" and "Custom Width & Height" without a standard list to read from|kb_v2/catalog/catalog-product-labels.md; kb_v2/catalog/catalog-custom-shape-labels.md; kb_v2/catalog/catalog-window-decals.md
business_cards|-|no size row on any card page: the standard card page answers "Dimensions (LxH): Any custom sizes and measurements" and no page prints 3.5 x 2 in, so a card size comes from the visitor|kb_v2/catalog/catalog-standard-business-card.md
banners|23" x 66"; 24" x 81"; 33" x 81"; 47" x 81"|pull-up banners are the only published size list in the corpus; every other sign page answers custom width and height, and "or custom" is offered alongside these four|kb_v2/catalog/catalog-pull-up-banners.md; kb_v2/catalog/catalog-window-decals.md
print|3.5" x 8.5"; 3.5" x 11"|tear-card sizes are spec bullets; door-hanger sizes (3.5" x 8.5", 4.25" x 11", 5.5" x 17") appear only in FAQ prose while the page's own Sizes section says none is published, so they are not listed here; no other print product publishes a size|kb_v2/catalog/catalog-custom-tear-cards.md; kb_v2/catalog/catalog-door-hanger.md
```

## Gauges

`basis` says how much weight the figure carries: `page` is a spec bullet, `faq` is a Q&A answer on a product page, `knowledge` is a hub article that never claims the figure is ours to quote.

```capability
# table: gauges
# family|material|gauge|basis|source|note
boxes|kraft board|80 lb to 100 lb|page|kb_v2/catalog/catalog-tuck-boxes.md|spec bullet, same wording on the food & beverage category page
boxes|rigid paperboard|800 to 1200 gsm|faq|kb_v2/catalog/catalog-tuck-boxes.md|the only gsm range the corpus attaches to a named box stock
boxes|corrugated board, bux board, grayboard, cardstock, kraft|12 pt to 28 pt (60 lb to 400 lb)|page|kb_v2/catalog/catalog-custom-hoodie-packaging.md|one bullet covers the whole stock list; the source never splits the range by material
boxes|paperboard|12 pt to 28 pt|faq|kb_v2/catalog/catalog-cbd-cream-boxes.md|the answer says "usually around" and calls it customizable; it names no material
boxes|rigid cardboard and paperboard|18 pt to 24 pt|faq|kb_v2/catalog/catalog-tea-bag-dispenser.md|stated for crush resistance
business_cards|cardstock|13 pt, 14 pt, 16 pt, 18 pt|page|kb_v2/catalog/catalog-standard-business-card.md|spec bullets; the page's Materials list is multi-material
business_cards|cardstock|12 pt, 14 pt or 16 pt, 18 pt or 24 pt|faq|kb_v2/catalog/catalog-folded-business-card.md|advice by use (bulk mailer / pocket / premium)
business_cards|cardstock|32 pt|page|kb_v2/catalog/catalog-ultra-thick-business-cards.md|also 32 pt linen on the linen page and 32 pt raised foil on the premium page
business_cards|coated board|16 point|faq|kb_v2/catalog/catalog-embossed-gloss-business-cards.md|the same answer gives 20 mil PVC or PETG for the plastic version
business_cards|PVC, PETG|20 mil|faq|kb_v2/catalog/catalog-embossed-gloss-business-cards.md|water and tear resistance
business_cards|cardstock (tent cards)|12 to 24 point|knowledge|kb_v2/knowledge/know-business-cards-tent-card-standing-business-card-guide.md|hub article, not a product page
print|gloss paper, high-finish and uncoated paper|70 lb to 100 lb|page|kb_v2/catalog/catalog-brochures.md|same wording on the political brochure page
print|high-finish and uncoated paper|60 lb to 75 lb|page|kb_v2/catalog/catalog-booklets.md|the page names no paper type beyond that
print|cardstock|10 pt|page|kb_v2/catalog/catalog-custom-political-postcards.md|adjacent Materials bullet
bags|metallized film|5 mil|faq|kb_v2/catalog/catalog-pre-roll-mylar-bags.md|stated as an oxygen, moisture and UV barrier
bags|metallized film|120 micron|faq|kb_v2/catalog/catalog-vape-pouches.md|named as beating the "high barrier" oxygen threshold
bags|laminate|80 micron|faq|kb_v2/catalog/catalog-vape-pouches.md|single-pod promo weight
bags|foil|80 micron|faq|kb_v2/catalog/catalog-flat-bottom-pouches.md|quoted inside a coffee shelf-life comparison
bags|compostable and recyclable constructions|80 to 150 micron|faq|kb_v2/catalog/catalog-eco-friendly-pouches.md|the answer says "across most constructions"
bags|PE|100 micron (about 4 mil) and 130 to 150 micron|faq|kb_v2/catalog/catalog-hemp-flower-mylar-bag.md|split by pack size, not by material; the page's own Materials bullet is Metalized+Clear
bags|PET|120 micron|faq|kb_v2/catalog/catalog-poly-mailers.md|suggested for pointed parts
banners|vinyl|13 oz, 18 oz|faq|kb_v2/catalog/catalog-step-and-repeat-banners.md|matte stretch polyester is named alongside, without a weight
banners|scrim vinyl|13 oz to 18 oz per square yard|knowledge|kb_v2/knowledge/know-signs-and-banners-what-are-scrim-vinyl-banners-durable-guide.md|hub article
banners|mesh|8 oz per yard|knowledge|kb_v2/knowledge/know-signs-and-banners-what-are-mesh-banners-and-why-theyre-taking-over-signs.md|hub article, compared against 13 oz vinyl
banners|backlit vinyl|15 to 20 oz per square yard|knowledge|kb_v2/knowledge/know-signs-and-banners-what-is-backlit-vinyl-and-what-does-it-mean.md|hub article
banners|coroplast|4 mm, 6 mm, 8 mm|knowledge|kb_v2/knowledge/know-signs-and-banners-what-are-corrugated-plastic-coroplast-compositions.md|hub article; the yard-sign guide repeats 4 mm as standard
banners|PVC board / Sintra|3, 5, 10, 19 mm|knowledge|kb_v2/knowledge/know-signs-and-banners-what-is-pvc-board-sintra-expanded-pvc-a-clear-guide-for-signs-and-banners.md|hub article
banners|acrylic|1/8 in to 1 in|knowledge|kb_v2/knowledge/know-signs-and-banners-what-are-acrylic-signs-how-they-deliver-real-efficiency.md|hub article; 3/16 in and 1/4 in named as the popular sign thicknesses
labels|none published|-|-|-|no label, sticker or decal page in kb_v2 states a face-stock gauge in pt, mil, micron or gsm
```

## Questions for production

```capability
# table: needs_production
# family|question|asked|source
banners|which sign products are ours as a line: Signicades, desk name plates, restroom signs, parking signs and A-frames are named by the signs category page but publish no specs|sales and production|kb_v2/catalog/catalog-signicades.md
print|coasters, mugs, keychains, envelopes, wall calendars, posters, numbered tickets and variable printing have pages but no specs and no category listing; are these live product lines?|sales|kb_v2/catalog/catalog-coaster.md; kb_v2/catalog/catalog-mugs.md; kb_v2/catalog/catalog-keychain.md
boxes|is supplements-packaging a seventh catalogue family or part of boxes? The site gives it its own category prefix and one page|sales|kb_v2/catalog/catalog-supplements-packaging.md
bags|which film constructions are actually stocked, and which gauge do we quote for a given pack size? Every gauge in the corpus is an FAQ answer that names no material or splits by size|production|kb_v2/catalog/catalog-hemp-flower-mylar-bag.md
labels|no label page publishes a face-stock thickness, so which stock do we quote for freezer, outdoor and UV exposure?|production|kb_v2/catalog/catalog-barcode-labels.md
boxes|flute profiles are listed with no thickness, ECT or ply figure anywhere in the corpus: what do we actually specify for E, B, C, EB and BC flute?|production|kb_v2/catalog/catalog-category-food-beverage-boxes.md
print|the mug page reads as a copyright condition but the sentence is garbled; can we repeat any copyright rule to a visitor?|legal|kb_v2/catalog/catalog-mugs.md
bags|is the published WVTR figure (below 0.1 g/m2/day) ours to state, and where is the test report?|production and legal|kb_v2/catalog/catalog-hemp-flower-mylar-bag.md
```

## Not attested

Values that must not appear in an answer as something we make. `class: probe` rows are the negative probes the bot must fail; `class: v1-absent` rows are what the old six-page vocabulary claimed and kb_v2 never says - they are kept for the auditor, and the primer lists only the probes, because 80 absent values in the prompt would push the useful ones out.

```capability
# table: not_attested
# family|value|note|class
boxes|pillow box|described generically in the folding-carton hub; no product page offers one, so we do not say we make it|probe
boxes|sleeve box|the phrase "Sleeves use 40% less material than full boxes" appears in FAQ prose on a box category page; no sleeve product page exists|probe
boxes|rigid mylar box|mixes a bag material with a box form; neither page pairs them|probe
bags|Child-Guard zipper|the brand name does not appear anywhere in kb_v2; the mechanisms the site names are push-and-pull, push-and-slide, press-to-close and pinch-and-pull|probe
bags|squeeze-then-slide zipper|phrasing not in kb_v2; see the four mechanisms the site does name|probe
labels|braille embossing|in the v1 vocabulary; no label or card page in kb_v2 mentions braille|probe
print|letterpress|not in kb_v2; the print pages name offset, digital, screen and flexographic|probe
bags|high-barrier metalized foil|v1 vocabulary (bags/material); the string does not occur anywhere in kb_v2|v1-absent
bags|metalized + clear front|v1 vocabulary (bags/material); the string does not occur anywhere in kb_v2|v1-absent
bags|kraft paper laminate|v1 vocabulary (bags/material); the string does not occur anywhere in kb_v2|v1-absent
bags|clear/transparent film|v1 vocabulary (bags/material); the string does not occur anywhere in kb_v2|v1-absent
bags|kraft film|v1 vocabulary (bags/material); the string does not occur anywhere in kb_v2|v1-absent
bags|compostable multi-layer|v1 vocabulary (bags/material); the string does not occur anywhere in kb_v2|v1-absent
bags|metalized foil|v1 vocabulary (bags/finish); the string does not occur anywhere in kb_v2|v1-absent
bags|kraft paper laminate|v1 vocabulary (bags/finish); the string does not occur anywhere in kb_v2|v1-absent
bags|metalized + clear front|v1 vocabulary (bags/finish); the string does not occur anywhere in kb_v2|v1-absent
bags|copper foil|v1 vocabulary (bags/finish); the string does not occur anywhere in kb_v2|v1-absent
bags|rose-gold foil|v1 vocabulary (bags/finish); the string does not occur anywhere in kb_v2|v1-absent
bags|AQ coating|v1 vocabulary (bags/finish); the string does not occur anywhere in kb_v2|v1-absent
bags|Euro hole|v1 vocabulary (bags/extras); the string does not occur anywhere in kb_v2|v1-absent
bags|Child-Guard zipper|v1 vocabulary (bags/extras); the string does not occur anywhere in kb_v2|v1-absent
bags|easy-open standard zipper|v1 vocabulary (bags/extras); the string does not occur anywhere in kb_v2|v1-absent
boxes|none|v1 vocabulary (boxes/insert); the string does not occur anywhere in kb_v2|v1-absent
boxes|die-cut foam insert|v1 vocabulary (boxes/insert); the string does not occur anywhere in kb_v2|v1-absent
boxes|die-cut cardboard insert|v1 vocabulary (boxes/insert); the string does not occur anywhere in kb_v2|v1-absent
boxes|tamper-evident glue pattern|v1 vocabulary (boxes/insert); the string does not occur anywhere in kb_v2|v1-absent
boxes|braille embossing|v1 vocabulary (boxes/insert); the string does not occur anywhere in kb_v2|v1-absent
boxes|copper foil|v1 vocabulary (boxes/finish); the string does not occur anywhere in kb_v2|v1-absent
boxes|rose-gold foil|v1 vocabulary (boxes/finish); the string does not occur anywhere in kb_v2|v1-absent
boxes|AQ coating|v1 vocabulary (boxes/finish); the string does not occur anywhere in kb_v2|v1-absent
boxes|full-colour print|v1 vocabulary (boxes/finish); the string does not occur anywhere in kb_v2|v1-absent
labels|silver film|v1 vocabulary (labels/material); the string does not occur anywhere in kb_v2|v1-absent
labels|foil gold|v1 vocabulary (labels/finish); the string does not occur anywhere in kb_v2|v1-absent
labels|foil silver|v1 vocabulary (labels/finish); the string does not occur anywhere in kb_v2|v1-absent
labels|foil rose|v1 vocabulary (labels/finish); the string does not occur anywhere in kb_v2|v1-absent
banners|vinyl 9 oz|v1 vocabulary (banners/material); the string does not occur anywhere in kb_v2|v1-absent
banners|vinyl 10 oz|v1 vocabulary (banners/material); the string does not occur anywhere in kb_v2|v1-absent
banners|vinyl 13 oz|v1 vocabulary (banners/material); the string does not occur anywhere in kb_v2|v1-absent
banners|vinyl 15 oz|v1 vocabulary (banners/material); the string does not occur anywhere in kb_v2|v1-absent
banners|vinyl 18 oz|v1 vocabulary (banners/material); the string does not occur anywhere in kb_v2|v1-absent
banners|vinyl 20 oz|v1 vocabulary (banners/material); the string does not occur anywhere in kb_v2|v1-absent
banners|vinyl 22 oz|v1 vocabulary (banners/material); the string does not occur anywhere in kb_v2|v1-absent
banners|heat-welded hem|v1 vocabulary (banners/finish); the string does not occur anywhere in kb_v2|v1-absent
banners|CMYK print|v1 vocabulary (banners/finish); the string does not occur anywhere in kb_v2|v1-absent
business_cards|any Pantone colour|v1 vocabulary (business_cards/finish); the string does not occur anywhere in kb_v2|v1-absent
business_cards|NFC tap profile|v1 vocabulary (business_cards/extras); the string does not occur anywhere in kb_v2|v1-absent
print|weather-proof stock|v1 vocabulary (print/finish); the string does not occur anywhere in kb_v2|v1-absent
print|Z-fold|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|gate-fold|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|accordion-fold|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|roll-fold|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|french fold|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|cross-fold|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|double parallel fold|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|step-down|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
print|poster-style|v1 vocabulary (print/fold); the string does not occur anywhere in kb_v2|v1-absent
```

## Aliases

The written forms the site uses for one value, so a visitor's spelling resolves instead of reading as an invented noun. `bot/capability.py::normalise` folds a query through this table before it builds a tuple key; the builder folds the same pairs at extraction time via MERGE, so the two never drift apart.

```capability
# table: aliases
# variant|canonical
3 dimensional raised uv|3D raised UV
3 dimensional raised uv effects|3D raised UV
aq coating|aqueous coating
aqueous|aqueous coating
buxboard|bux board
card board|cardboard
carry handles|handle
child resistant zippers|child-resistant zipper
clear transparent film|clear film
clear window|window
color customization|colour customization
corflute|corrugated plastic
corrugated|corrugated board
corrugated e flute|e-flute
corrugated plastics|corrugated plastic
corrugated stock|corrugated board
corrugated substrates|corrugated board
cut outs|cut-out
die cut foam insert|foam insert
die cutting|die cut
e flute corrugated|e-flute
easy open standard zipper|easy-open zipper
easy open zippers|easy-open zipper
euro holes|Euro hole
foam inserts|foam insert
foil gold|gold foil
foil rose|rose gold foil
foil silver|silver foil
gloss laminate|gloss lamination
gloss laminated|gloss lamination
glossy|gloss
gold foiling|foil printing
greyboard|grayboard
handles|handle
hang holes|hang hole
heat sealed|heat seal
high barrier metalized foil|metalized foil
hot stamp|hot foil stamping
hot stamp foiling|hot foil stamping
inside glass|reverse printing
kiss cutting|kiss cut
layered reveal mechanisms|layered reveal mechanism
led light modules|LED light module
lift tabs|lift tab
magnetic closures|magnetic closure
matte laminate|matte lamination
matte laminated|matte lamination
metallized film layer|metallized film
molded pulp trays|molded pulp tray
mylar bags|mylar bag
paperboard dividers|paperboard divider
perforations|perforation
polyethylene|PE
polyethylene terephthalate|PET
polypropylene|PP
raised inks|raised ink
raised uv|3D raised UV
resealable tabs|resealable tab
ribbon pulls|ribbon pull
rigid|rigid board
rigid grayboard|grayboard
rigid stocks|rigid board
sbs|SBS paperboard
sheen aqueous|aqueous coating
softtouch|soft touch
softtouch lamination|soft touch lamination
spot foil|spot foiling
spotuv|spot UV
stackable designs|stackable design
tabs|lift tab
tamper evident features|tamper-evident seal
tamper evident glue pattern|tamper-evident seal
textured papers|textured paper
transparent polyester|polyester
uv|UV coating
varnishing|varnish
velvet lined trays|velvet-lined tray
vent holes|vent hole
weather proof stock|weatherproof stock
```

## Catalogue pages with no family

```capability
# table: unmapped
# page|title|kind
catalog-best-sellers|Best Sellers|other
catalog-coaster|Coasters|product
catalog-deals-nfc|NFC Card|deal
catalog-keychain|Keychains|product
catalog-mugs|Custom Printed Mugs|product
```
