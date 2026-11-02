# Capability sign-off packet - D-2 (registry) and D-10 (compliance allow-list)

Generated 2026-10-30 from `kb/capabilities/capability-registry.md`. That file is produced by
`chatbot/tools/build_registry_v2.py` reading the **kb_v2 corpus (469 files, all `status: verified`)** -
199 catalogue pages, 260 hub articles, 10 site pages. Nothing in this packet was typed by hand.

**What signing does.** Every row is `approved: pending`, so today the bot may *discuss* all 147
products and may *assert* none of them as a capability. Writing a name and date against a group flips
those rows to `approved: <name>, <date>` in the registry, and only then may the bot state that build
in a reply. Signing one family signs nothing else; **partial sign-off is a safe state** and does not
block the bot from running.

**What signing does not do.** This packet does not cover compliance language (section 6) and it is
not the counsel check (D-1), which is a separate gate before any live answering of regulated
questions.

---

## 1. The offering list - 147 product pages, sign per family

Each row is one product page and carries the options that page lists. The page URL is the row's
source in the registry file. "Site-listed" means the site's own category page put the product in that
family; "title-only" means the family was inferred from the page title and URL, so the *family* is
our reading, not the site's.

- [ ] **Boxes - 42 rows** (23 site-listed, 19 title-only)
  Boxes With Lid, CBD Boxes, CBD Cream Boxes, Christmas Gift Boxes, Cigar Boxes, Comic Book Boxes,
  Cookie Boxes, Cupcake Boxes, Dietary Supplement packaging, Display Box With Logo, Double Tea Box
  with Magnetic Closure, Eyelash Boxes, Foundation Boxes, Gold Foil Boxes, Hemp Boxes, Holographic
  Foiling Boxes, Hoodie Packaging, Lip Balm Boxes, Luxury Clothing Packaging, Mailer Boxes, Match
  Boxes, Medical Box with insert, Medicine Boxes, Metalized Boxes, Muffin Boxes, Perfume Boxes,
  Pharmaceutical Patch Box, Pie Boxes, Pop Counter Display Tray, PR Boxes, Product Display Box, Rack
  display boxes, Shape Boxes, Sock Packaging Boxes, Standard Green Tea Boxes, Tea Bag Dispenser, Tea
  Tray and Lid Gift Boxes, Textured Boxes, Torch Boxes, Tuck Boxes, Underwear Packaging, Wallet Boxes
- [ ] **Labels & stickers - 30 rows** (22 site-listed, 8 title-only, **5 with no options at all**)
  Address Labels, Barcode Labels, Bottle Labels, Canning Labels, Clings, Cosmetic Labels,
  Cut-to-size Sticker Singles, Die Cut Labels, Domed 3D Labels, Domed 3D Stickers, Food Labels,
  Front-Adhesive Stickers, Heart Stickers, Hexagon Stickers, Holographic Labels, Holographic
  Stickers, Label Stickers, Metallic Labels, Name Labels, Political Bumper Stickers, Political
  Stickers, Product Labels, Round Labels, Shape Labels, Sheet Labels, **Shipping Labels (two separate
  pages)**, Vinyl Labels, Vinyl Stickers, Water Bottle Stickers
- [ ] **Bags & pouches - 21 rows** (**1 site-listed, 20 title-only**)
  3 Side Seal Pouches, Biodegradable StandUp Pouch, CBD Mylar Bags, Child-Resistant Pouches,
  Chocolate Mylar Bags, Christmas Gift Bags, Coffee Bags, Eco-Friendly Pouches, Flat Bottom Pouches,
  Hemp Flower Mylar Bag, Inside Printed Pouches, Mylar Bags, Plastics Bags, Poly Mailers, Pouches,
  Pre Roll Mylar Bags, Smell proof weed bags, Stand Up Pouches, Vape Cartridge Pouches, Vape
  Pouches, Weed Mylar Bags
- [ ] **Banners & signage - 23 rows** (23 site-listed, **15 with no options at all**)
  A-Frames, Angled Flags Banners, Banners Stands, Canopy Tents, Car Door Decals, Car Window Decals,
  Desk Name Plates, Metal Signs, Parking Sign, Pop Up Display, Pull up Banners, Rectangle Flags,
  Restroom Signs, Signicades, Step and Repeat Banners, Stretch Table Covers, Table Cloths, Table
  Runners, Tabletop signs, Vinyl Banner, Wall decals, Way Finding Sign, Window Decals
- [ ] **Business cards - 15 rows** (12 site-listed, 3 title-only)
  3D Pop-up Folding Business Cards With Character, Business Card with QR Code, Embossed Gloss
  Business Cards, Foil Accent Business Cards, Folded Business Cards, Glossy Business Cards, Kraft
  Business Cards, Linen Business Cards, Matte Business Cards, NFC Business Cards, Painted Edge
  Business Cards, Political Business Cards, Round Corner Business Card, Standard Business Cards,
  Ultra Thick Business Cards
- [ ] **Print - 16 rows** (6 site-listed, 10 title-only, **9 with no options at all**)
  Booklets, Bookmarks, Brochure Printing, Door hangers, Envelopes, Flyers, Greeting Cards,
  Invitations, Magnets, Numbered Tickets, Political Brochures, Political Postcards, Posters, Tear
  Cards, Variable Printing, Wall Calendars

## 2. Five things we need decided, not just approved

| # | The finding | What we need |
|---|---|---|
| 1 | **30 of the 147 rows name a product and no options** (15 banners, 9 print, 5 labels, 1 bag). The page exists but publishes no materials, finishes or extras, so signing them says "we sell this" and nothing more. | Confirm these are live lines. Anything discontinued should be removed, not signed. |
| 2 | **kb_v2 gives us no mechanical exclusion.** All 26 refusals below are use-case *rules* (surface, load, run length). None can be matched against a customer's tuple, because the pairs they would refuse are pairs the site actually sells - e.g. an open-front display box in rigid cardboard with a window is a product page. The tuple matcher in the bot is therefore idle until Sales names a real refusal. | Either name at least one combination we will not build at all, or agree the bot keeps refusing by sentence, not by tuple. |
| 3 | **`supplements-packaging` may be a seventh family.** The site gives it its own category prefix and one page; we currently fold it into boxes. | Sales call: seventh family, or boxes? |
| 4 | **The print family is a bucket.** Magnets, envelopes, wall calendars, posters and tickets sit in it, and 10 of its 16 rows were placed by title alone. | Approve the bucket as-is, or split signage / paper goods / promotional items. |
| 5 | **Two refusals contradict our own lists.** "Pillow boxes carry small light goods only" is a rule, while "pillow box" is on the never-offer list - we cannot both limit and disclaim it. And **17 of the 26 rules name a value that no product page in kb_v2 offers as an option** - the family's own vocabulary does not contain it (duplex board, CCNB, chipboard, construction paper, lined paperboard, seal-end boxes, wall signs, deep debossing, press-to-close zipper, reuse). They come from hub articles, which describe materials in general rather than our catalogue. | Confirm, per rule, whether the thing is ours at all. A rule about a product we do not sell is noise in the prompt. |

## 3. The 26 refusals the bot will state - sign each sentence

Everything here is a sentence the site itself writes. A signed line may be said to a visitor as the
reason we cannot do something; unsigned, the bot may only paraphrase it as "the team confirms".

| Family | Refusal | Page |
|---|---|---|
| labels | Static cling will not hold on textured or porous walls; the grip drops and the edge lifts | clings |
| banners | Car-window clings must not sit in the driver's direct line of sight (safety, not capability) | clings |
| labels | Front-adhesive decals are refused on textured or porous surfaces | front-adhesive stickers |
| labels | Vinyl front-adhesive is one-time; it loses its stick once removed, so reuse is not offered | front-adhesive stickers |
| labels | Sticky vinyl decals are long-term and not re-usable; only static cling is | window decals |
| labels | Paper stock labels are not made for water or weather; wet use needs a synthetic stock | cosmetic labels |
| labels | We will not print a food label on stock that cannot take cold storage, oil or handling | specialty labels |
| boxes | Open-front display boxes are shelf units, not durable for heavy shipping | display box with logo |
| boxes | Paperboard alone does not control temperature; coatings only block moisture | medicine boxes |
| boxes | Precision foam inserts suit uneven bottles but hurt the pack's recyclability | perfume boxes |
| business cards | Foil runs under 1,000 are refused for machine set-up, not price: print 1,000 and split | foil accent cards |
| bags | Foil-lined structures are multi-layer; some recycling streams reject them, so no curbside claim | child-resistant pouches |
| bags | Thin film cannot hold a deep debossed impression; the hub limits it to thicker bags | mylar hub |
| bags | Flexographic printing is refused for short runs and for designs that keep changing | mylar hub |
| bags | Flexographic printing is not quoted for photo-level sharp detail | mylar hub |
| bags | A press-to-close zipper is not sold as a replacement for the original heat-seal barrier | mylar hub |
| bags | A standard sealed pouch is unsuitable for products that keep releasing gas unless a degassing valve is added | mylar hub |
| bags | Not every vacuum pouch is heat-safe; check the product specification | mylar hub |
| banners | The wrinkle-free fabric sign grade is explicitly not recommended for exterior UV and rain | wall signs hub |
| boxes | Pillow boxes carry small, light goods only, not heavy items | folding-carton hub |
| boxes | A seal-end box is not meant for products the customer opens and closes repeatedly | folding-carton hub |
| boxes | Duplex board is ruled out for very heavy or delicate products | folding-carton hub |
| boxes | CCNB is not offered for heavy-duty use | folding-carton hub |
| boxes | Lined paperboard is not supported for heavy products | folding-carton hub |
| boxes | Chipboard cannot take very heavy weight; it is a shape-and-structure stock | folding-carton hub |
| print | Construction paper is ruled out for detailed printing; the surface is rough | folding-carton hub |

## 4. Eight questions this corpus cannot answer - who owns each

| Ask | Question | Owner |
|---|---|---|
| banners | Which sign products are ours as a line? Signicades, desk name plates, restroom signs, parking signs and A-frames are named by the category page but publish no specs | sales + production |
| print | Coasters, mugs, keychains, envelopes, wall calendars, posters, numbered tickets and variable printing have pages but no specs and no category listing - live lines? | sales |
| boxes | Is `supplements-packaging` a seventh family or part of boxes? | sales |
| bags | Which film constructions are stocked, and which gauge do we quote for a given pack size? Every bag gauge in the corpus is an FAQ answer that names no material or splits by size | production |
| labels | No label page publishes a face-stock thickness - which stock do we quote for freezer, outdoor and UV exposure? | production |
| boxes | Flute profiles are listed with no thickness, ECT or ply figure anywhere - what do we specify for E, B, C, EB, BC? | production |
| print | The mug page's copyright sentence is garbled - may we repeat any copyright rule to a visitor? | legal |
| bags | Is the published WVTR ("below 0.1 g/m2/day", hemp-flower pouch FAQ) ours to state, and where is the test report? | production + legal |

## 5. Five catalogue pages we could not place in any family

Coasters, Keychains and Custom Printed Mugs have product pages with a quote form but no family
listing; NFC Card sits under a deal URL; Best Sellers is an index. They contribute vocabulary only.
Tell us which are real products and they become rows.

## 6. What sizes and gauges may be said out loud

Two families publish a size grid at all: **banners** (23x66, 24x81, 33x81, 47x81 in, pull-up only)
and **print** (3.5x8.5 and 3.5x11 in, tear cards only). Boxes, bags, labels and cards answer "any
size", so a size for those must come from the visitor or from Sales - the bot is forbidden to
calculate or imply one.

Of 29 gauge figures, **7 come from a product spec bullet** (kraft board 80-100 lb, the hoodie stock
list 12-28 pt, business card 13/14/16/18 pt, 32 pt, brochure 70-100 lb, booklet 60-75 lb, political
postcard 10 pt). **22 come from an FAQ answer or a hub article** and the bot must not quote them; it
says the team confirms the gauge with the quote. **Labels publish no face-stock gauge anywhere.**
Flutes publish no thickness or ECT.

## 7. D-10, the compliance allow-list - not ready to sign

The allow-list in `kb/capabilities/compliance-allowlist.md` still cites **v1 `kb/` files**, not
kb_v2, and every contradiction below was re-checked against kb_v2 this week. It should not be signed
until it is re-sourced; re-sourcing changes which sentences are allowed, not just where they came from.

| The site (kb_v2) says | The v1 allow-list currently says | Needs |
|---|---|---|
| "All of our materials are FDA-compliant and safe for direct contact with food" | Never say all our pouches are FDA approved; keep "on demand" | One ruling on the sweeping sentence |
| "carry full FDA food-contact approval" (biodegradable pouch FAQ); "FDA-approved virgin chipboard" | "food safe" and "FDA certified" are banned; no certificate number is published anywhere in the corpus | Production to name the actual certificate, or the phrases stay banned |
| Decal/label pages answer "yes, fully dishwasher-safe" for a commercial dishwasher | Water-resistant, not waterproof; "dishwasher safe" is on the never list | Sales: which line may say it |
| Hemp-flower FAQ states WVTR below 0.1 g/m2/day | Never name a barrier test value; no test report on file | Legal/production ruling (row 8 above) |
| FSC appears only in hub articles, never on a product page | FSC certified is banned | Keep banned unless a certificate is produced |
| Prop 65 appears nowhere in kb_v2 | (no row) | Counsel: is a Prop 65 warning sentence needed at all? |
| MOQ is per product and inconsistent (500 jelly boxes, 1000 popcorn boxes and coffee bags, 2000 elsewhere) | (no row) | Sales: the MOQ the bot may state, by family |
| The About page membership lists contradict each other across site pages | Printing United Alliance only, and never as a certification | Confirm one exact membership sentence |

**Named approver for the allow-list (D-10 requires a name on the file, still empty):**
`approver: ______  date: ______`

---

## Sign-off

| Scope | Name | Role | Date | Initials |
|---|---|---|---|---|
| Section 1 - the 147 offering rows (per family, tick above) | | sales | | |
| Section 1 - materials, gauges, combinations | | production | | |
| Section 2 - the five decisions | | owner | | |
| Section 3 - the 26 refusal sentences | | sales + production | | |
| Section 7 - compliance allow-list (D-10) | | counsel or owner | | |

Anything left unsigned stays `approved: pending`, which is a safe state: the bot discusses it and
does not assert it.
