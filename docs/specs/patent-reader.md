# Patent reader: functional specification

This is a behavioural specification for a patent reading view, written from
observing an existing product (PatentMonk, 2015). It describes what the
reader does for the person using it. It contains no source code, identifiers
or text from that product; the implementation in this repository is written
from this document and public USPTO data only.

Section numbers (R1, R2, ...) are referenced from the code.

## R1. Loading a patent

* The reader opens a patent, publication or application by number from the
  address (for example `/patent?n=6777777`) or from a search box in the page.
* Loading shows a busy overlay until the data arrives.
* Opening another patent from inside the reader (a citation link, the search
  box) replaces the content in place without a full page reload, updates the
  address, and adds a history entry. The browser's back and forward buttons
  load the corresponding patent again.
* Input that is not a recognisable number is treated as a search query (R11).
* After a load the page scrolls to the top.

## R2. Header and identity

* The number is shown in a readable form: a US patent as "U.S. 6,777,777"
  (thousands separators; a letter prefix such as D, RE or PP is kept in
  front of the digits); a publication or application number as given.
* The same label is used in the page title and in the sidebar heading.
* The title of the invention is shown as the main heading.

## R3. Sections and what happens when data is missing

* Sections, in reading order: bibliographic table, claims, abstract,
  description, patent citations, citing patents ("referenced by"),
  classifications, legal events.
* A section with no data is hidden together with its navigation entry.
* Citations, citing patents, classifications and legal events are tables.

## R4. Bibliographic table

* Rows: publication number and kind, publication type, application number,
  publication date, filing date, priority date, fee or legal status, related
  publications ("also published as"), inventors, original assignee, citation
  export links, and external links (USPTO record, assignment record, a
  family/register service).
* Rows whose meaning is an assumption (priority date, fee status) carry a
  small help icon with an explanatory tooltip.
* A long list of related publications starts collapsed behind a single link;
  activating it expands the full list in place, each entry a patent link (R6).
* Inventor and assignee names are links that run a search for other patents
  by that person or company.
* Citation export offers BibTeX, EndNote and RIS downloads.

## R5. Navigation sidebar

* A fixed sidebar lists: the patent number (top of page), Abstract, Claims,
  Description, and under Description one entry per description heading
  (shown in sentence case), then Citations, Referenced by, Classifications,
  Legal events. While showing search results it lists the result numbers.
* Selecting an entry scrolls smoothly (about 0.4 s) to the section and then
  briefly flashes the heading in the accent colour (fade in, hold, fade out
  over roughly 1.5 s).
* Scroll spy: as the reader scrolls, the entry for the section currently at
  the top of the viewport is marked active. If the sidebar list is taller
  than the window, it scrolls itself to keep the active entry visible, except
  while the pointer is over the sidebar.
* The sidebar can be collapsed and reopened; the choice is remembered. On
  narrow screens it slides over the content with a dimming mask, and
  selecting an entry closes it.
* The top bar hides when the page is scrolled down and reappears when the
  pointer approaches the top edge or the page is scrolled back to the top.

## R6. Hover previews of other patents

* Every link to another patent on the page (citations, citing patents,
  related publications, search results) is a patent link.
* Resting the pointer on a patent link for about half a second shows a
  preview card beside it: a heading with the formatted number, the title,
  a small image of the patent's first page (about 100 px wide) floated left,
  and the abstract text.
* The card's data is fetched the first time a link is hovered and reused
  afterwards. If the pointer has left before the data arrives, no card is
  shown. Only one card is visible at a time.
* Clicking a patent link opens that patent in the reader (R1) and closes any
  open card.
* Cards for links in the bibliographic table open to the left; elsewhere to
  the right.

## R7. Reference numerals and figure labels linked to drawings

This is the central feature.

* The drawings are a set of sheets (images). For each sheet the system knows
  which labels appear on it: figure labels ("FIG. 3") and reference numerals
  ("128", "10a").
* In the original product this per-sheet label list came from running OCR on
  the drawing images on the server after the page loaded.
* In the description text, every figure mention and every reference numeral
  that appears on at least one sheet becomes an active label. Numerals with a
  letter suffix (a digit run followed by a letter, sometimes typeset as a
  separate italic letter) are matched as one label. Longer labels are matched
  before shorter ones so "128" is not split into "12" and "8".
* Hovering an active label shows a popover with the image of every sheet on
  which the label appears, side by side, each captioned "Drawing N". The
  images together take at most about half the window's width and height.
* The popover is placed so it stays on screen: to the left of labels near the
  right edge, to the right of labels near the left edge, otherwise below
  labels near the top of the window and above all others.
* The popover stays open while the pointer is over the label or over the
  popover itself, and closes shortly (about 0.1 s) after the pointer leaves
  both.
* Clicking an image in the popover opens the drawing gallery (R8) at that
  sheet. Clicking the label itself does not navigate.

## R8. Drawing strip and gallery

* A narrow strip of sheet thumbnails sits at the right edge of the page. It
  slides in automatically the first time the reader scrolls past the start of
  the drawings description, and a tab toggles it in and out at any time.
* Clicking a thumbnail opens a full-window gallery at that sheet.
* Gallery controls: previous and next (also the left and right arrow keys),
  space toggles a slideshow, a zoom slider from 0.75x to 5x, rotate by 90
  degrees per press (cycling back to 0 after 270), drag to pan the image, a
  reset button that restores zoom, rotation and position, and a close
  control. Clicking the backdrop closes the gallery.
* Zoom and rotation apply to the current sheet only; moving to another sheet
  shows that sheet's own state.

## R9. Claims

* Next to the Claims heading, two counts: independent claims and all claims,
  each with a tooltip. If there are no independent claims the counts are
  hidden.
* Clicking a count opens a dialog titled "Independent" or "All" listing those
  claims, independent claims separated by rules. The dialog opens scrolled to
  the top.
* Independent and dependent claims are styled differently. References to
  other claims ("claim 1") link to that claim.

## R10. Reading preferences

* Settings: text size (small, regular, large), typeface (serif or sans
  serif), dark reading mode (dark page and tables with light text), a
  decorative full-page background image on or off, and the background shown
  normally or colour-inverted.
* A reset control restores all defaults.
* Settings persist between visits and are applied before the content is
  shown.

## R11. Search within the reader

* The search box accepts a number or free text. A number opens the patent;
  anything else runs a search.
* Results: the heading shows the result count ("N Search Results"); each
  result shows the title (link), a first-page thumbnail (with a placeholder
  if the image fails), the reader address of the patent, and a text snippet.
  All parts are patent links (R6) and open the patent in the reader.
* Eight results per page, up to eight pages, with numbered page buttons and
  previous/next buttons disabled at the ends. The pagination appears above
  and below the results. No results shows a short "try again" message.
* While results are shown, the patent-only sections and controls are hidden.

## R12. PDF and sharing

* Read the PDF in a viewer, download the PDF, and email the PDF to one or
  more addresses (address fields can be added and removed in the dialog).
* A link to the same patent on an external full-text service.
* A favourite toggle (star) per patent and a view counter.

## Not carried over

Analytics, social-network buttons, the browser-extension installer and
extension messaging, and the third-party search service are not part of
this specification.

## Implementation notes for Bumper (USPTO data)

| Spec | Source in Bumper |
| --- | --- |
| R1 | `/patent` page; `/api/patent/read` resolves numbers via `lookup.normalize` / `Service.resolve` |
| R2-R4 | ODP application record (biblio, inventors, applicant, status, continuity) and the per-patent full-text XML (`grantDocumentMetaData.fileLocationURI`) for title, abstract, claims, description, citations, classifications |
| R3 "referenced by" | Not available from ODP; shown when the cited-by data is loaded locally, otherwise hidden |
| R3 legal events | ODP transaction history (`eventDataBag`) |
| R6 | `/api/preview` and `/api/patent/thumb` |
| R7 | Per-sheet labels from OCR (`tesseract`) when installed; otherwise derived from the description text (`bumper/drawings.py`: numerals tagged bold in the USPTO XML, attributed to the figures discussed, figures to sheets) |
| R8 | Sheet images rendered from the USPTO PDF pages (`drawings.sheet_pages` locates the sheets) |
| R10 | Preferences stored in `localStorage` |
| R11 | Numbers open the reader; other text searches loaded patent full text |
| R12 | PDF view and download via `/api/patent/pdf`; email is left to the person's own mail client (`mailto:` with the PDF link) since Bumper runs no mail server; favourites stored in `localStorage` |
