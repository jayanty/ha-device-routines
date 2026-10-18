# Publication

Everything Device Routines needs to be listed in the HACS default list, prepared in this
repository and opened nowhere. The icon and logo ship inside the integration, in
`custom_components/device_routines/brand/`, which Home Assistant 2026.3 and later shows
and the HACS brands check accepts, so no `home-assistant/brands` pull request is needed
(decision L78). Each outward facing step is the owner's: the owner does it, or tells a
session in chat to do it under the owner's account (plan Section 6.4). Nothing here has
been opened, submitted or changed on GitHub.

| Owner log | Item | Gates |
| --- | --- | --- |
| O10 | Approve the icon and logo | The images that ship in `v1.0.0`; nothing outward facing |
| O11 | Go ahead for the HACS default submission, including the repository description and topics | Listing in HACS without a custom repository |
| O12 | The console look that gates the `v1.0.0` tag | The release the HACS submission points at |

The texts below are public once opened. They name no real home, device, area, person or
address, only the project, its repository `jayanty/ha-device-routines` and generic
examples.

## Order of the steps

| Step | What | Who | Owner log | When |
| --- | --- | --- | --- | --- |
| 1 | Look at the [brand images](#the-brand-images) and approve them, or say what to change | Owner | O10 | Before `v1.0.0`, which ships them; a change is a redraw by `tools/make_brand.py` |
| 2 | Set the [repository description and topics](#repository-description-and-topics), and check that issues are enabled | Owner, or a session on the owner's go ahead | O11 | Before step 4 |
| 3 | Release `v1.0.0` with CI green. The `hacs` job ignores no check since L78, so this is the release the HACS submission asks for: made after the checks passed with nothing ignored. If `v1.0.0` is tagged before L78 is on `main`, release a patch (`v1.0.1`) after it instead | Session | O12 | After live validation B and O12 |
| 4 | Open the [HACS default submission](#the-hacs-default-submission) | Owner, or a session on the owner's go ahead | O11 | After steps 2 and 3 |
| 5 | When the submission has merged: switch the README's HACS badge and install steps from custom repository to default (see [After the listing](#after-the-listing)) | Session | O11 | After the merge |

The channel switch of the owner's own instance (O13) is separate and can happen before,
between or after these steps.

## The brand images

`tools/make_brand.py` draws every image; run `.venv/bin/python -m tools.make_brand` to
write them and `.venv/bin/python -m tools.make_brand --check` to compare the committed
files with a fresh drawing. The same bytes sit in two places:
`custom_components/device_routines/brand/`, the folder Home Assistant reads a custom
integration's images from (it ships in the release zip, and HACS installs it with the
integration), and `brand/`, which the README's images link to.

| File | Size (px) | What it is |
| --- | --- | --- |
| `icon.png` | 256 x 256 | The icon |
| `icon@2x.png` | 512 x 512 | The icon for high density screens |
| `logo.png` | 552 x 128 | The icon and the words "Device Routines" in dark grey, for light backgrounds |
| `logo@2x.png` | 1104 x 256 | The same at twice the size |
| `dark_logo.png` | 552 x 128 | The logo with white words, for the dark theme |
| `dark_logo@2x.png` | 1104 x 256 | The same at twice the size |

The icon follows the integration's `mdi:calendar-clock` idea in Home Assistant's flat
style, drawn for this project rather than copied: a blue calendar (`#03A9F4`) with a darker
header band (`#0288D1`) and two navy rings (`#01579B`), and in front of its lower right
corner a clock with a white face and a `#0288D1` rim whose navy hands show three o'clock,
set apart from the calendar by a transparent gap. It has no text and reads on light and
dark backgrounds down to 24 px, so there is no `dark_icon.png`; where a `dark_` image is
missing, `icon.png` is shown. The words of the logo are set in Aileron Regular from
dotcolon (`https://dotcolon.net/fonts/aileron`), released under CC0 1.0 (public domain)
and bundled with Pillow as its default font, with a light stroke for a medium weight. The
logo is not the icon alone.

Home Assistant names no image rules for the local folder beyond the file names. The
images follow the `home-assistant/brands` README's rules anyway: every image is a PNG in
RGBA with a transparent background, trimmed (something is drawn on every edge row and
column), without metadata, the icons square at 256 and 512 and the logos landscape with
a shortest side of 128 and 256. They are not interlaced, which the README prefers but
does not require.

What proves it, in `tests/test_repository.py`:

| Requirement | Test |
| --- | --- |
| Exactly these files, in both folders | `test_the_brand_files_are_exactly_the_drawn_set` |
| PNG, RGBA, transparent corners, not interlaced | `test_every_brand_image_is_an_rgba_png_with_transparent_corners` |
| Trimmed | `test_every_brand_image_is_trimmed` |
| Icons 256 and 512 square | `test_the_icons_are_square_at_256_and_512` |
| Logos landscape, shortest side 128 to 256, @2x exactly double | `test_the_logos_are_landscape_within_the_brands_limits` |
| The integration's folder holds the same bytes as `brand/` | `test_the_integrations_brand_folder_mirrors_brand` |
| The HACS brands check finds `brand/icon.png` under the content path | `test_the_hacs_brands_check_finds_the_icon_where_it_looks` |
| The `hacs` job ignores no check | `test_the_hacs_job_ignores_no_check` |
| The release zip carries `brand/` | `test_the_release_zip_carries_the_brand_folder` |
| The script draws the committed images, byte for byte | `test_make_brand_draws_the_committed_image_data`, `test_make_brand_reproduces_the_committed_files_byte_for_byte` |

## Repository description and topics

Owner log O11. Set on `jayanty/ha-device-routines`; HACS shows the description and uses the
topics for search, and its default list asks for both.

Description (163 characters, under GitHub's 350):

```text
Home Assistant custom integration: start and stop times, run timers and a plain language Schedule on every device page, backed by real, clearly marked automations.
```

Topics: the six of PRD 11.1 (`home-assistant`, `hacs`, `automation`, `blueprint`,
`schedule`, `timer`) plus four that Home Assistant users search for: `homeassistant`,
`home-assistant-integration`, `hacs-integration` and `home-automation`.

The commands (not run):

```bash
gh repo edit jayanty/ha-device-routines \
  --description "Home Assistant custom integration: start and stop times, run timers and a plain language Schedule on every device page, backed by real, clearly marked automations." \
  --homepage "https://github.com/jayanty/ha-device-routines/blob/main/docs/user-guide.md" \
  --enable-issues \
  --add-topic home-assistant --add-topic hacs --add-topic automation \
  --add-topic blueprint --add-topic schedule --add-topic timer \
  --add-topic homeassistant --add-topic home-assistant-integration \
  --add-topic hacs-integration --add-topic home-automation
gh repo view jayanty/ha-device-routines \
  --json description,repositoryTopics,hasIssuesEnabled,isArchived,visibility
```

## The HACS default submission

Owner log O11. Repository `hacs/default`, one line added to the file that lists
integrations (`integration`), in the list's order.

Before opening, check (step owner):

- [ ] The repository is public, not archived, has issues enabled, a description and the
      topics above.
- [ ] `hacs.json` and `manifest.json` are as HACS needs them (`tests/test_repository.py`
      checks the fields: `name`, `render_readme`, `zip_release`, `filename`,
      `homeassistant`; `domain`, `name`, `version`, `codeowners`, `documentation`,
      `issue_tracker`).
- [ ] The `hacs` job of `ci.yml` passes no `ignore` (L78; `test_the_hacs_job_ignores_no_check`).
- [ ] The `hacs` and `hassfest` jobs passed on `main` with nothing ignored, and their runs
      are linked in the body.
- [ ] A full release (not a pre release) with `device_routines.zip` was published after
      those runs: `v1.0.0`, or `v1.0.1` if `v1.0.0` came before L78 reached `main`.
- [ ] `jayanty/ha-device-routines` is not in the list yet.
- [ ] The owner opens it from the owner's own account: HACS asks that the submitter owns
      or maintains the repository.

The commands (not run):

```bash
gh repo fork hacs/default --clone
cd default
git switch -c add-device-routines
# Add "jayanty/ha-device-routines" to the file `integration`, where the list's order puts it.
git add integration
git commit -m "Adds new integration [jayanty/ha-device-routines]"
git push -u origin add-device-routines
gh pr create --repo hacs/default \
  --title "Adds new integration [jayanty/ha-device-routines]" \
  --body-file hacs-pr.md
```

Title:

```text
Adds new integration [jayanty/ha-device-routines]
```

Body (`hacs-pr.md`; fill in the three links, and paste the template's checklist over this
one if it has changed):

```markdown
## Repository

https://github.com/jayanty/ha-device-routines

Device Routines adds start and stop times, run timers and a plain language Schedule
sentence to Home Assistant device pages. Each routine is a normal automation built from a
blueprint the integration ships, so Home Assistant runs it and it keeps running without
the integration. An admin console lists every routine in the house.

## Checklist

- [x] I've read the publishing documentation.
- [x] I've added the HACS action to my repository.
- [x] (For integrations only) I've added the hassfest action to my repository.
- [x] The actions are passing without any disabled checks in my repository.
- [x] I've added a link to the action run on my repository below in the links section.
- [x] I've created a new release of the repository after the validation actions were run
      successfully.

## Links

Link to current release: https://github.com/jayanty/ha-device-routines/releases/tag/v1.0.0
Link to successful HACS action (without the `ignore` key): <link to the hacs job run>
Link to successful hassfest action (if integration): <link to the hassfest job run>
```

## After the listing

Session work once the HACS submission has merged:

- README: the badge `HACS custom repository` becomes `HACS default`
  (`https://img.shields.io/badge/HACS-default-41BDF5`, linking to `https://hacs.xyz/`),
  and the install steps start with searching for Device Routines in HACS; the custom
  repository steps stay below as the way to get pre releases early. The user guide's
  Installing section follows.
- The owner log closes O11 with the link of the merged pull request.

## Check against the current upstream rules before opening

The brand points below were checked against the upstream pages on 2026-10-18 (L78); the
HACS submission points were written from the documented rules as known when this file was
prepared. Before opening anything, the owner (or the session on the owner's go ahead)
compares these points with the current Home Assistant developer documentation, the HACS
action's brands validator, the HACS publishing documentation and the `hacs/default`
template:

1. Home Assistant, the local brand folder: a custom integration still ships its images in
   `custom_components/<domain>/brand/`, named `icon.png`, `dark_icon.png`, `logo.png`,
   `dark_logo.png` and an `@2x` of each, and they still take priority over the brands
   CDN; and whether any image rule (sizes, a file size limit, interlacing) now applies to
   that folder.
2. HACS, the brands check (`custom_components/hacs/validate/brands.py` in
   `hacs/integration`): it still passes when `<content path>/brand/icon.png` is in the
   repository tree.
3. HACS, requirements for the default list: a full release rather than tags or pre
   releases, the description and topics, issues enabled, and the HACS and hassfest
   actions passing without `ignore`.
4. HACS, the submission itself: the file that lists integrations and how it is ordered,
   the title format, the template's checklist and links, and whether the submitter must
   be the repository's owner.
5. HACS, `hacs.json`: that `name`, `render_readme`, `zip_release`, `filename` and
   `homeassistant` are still the keys it reads, and nothing it now requires is missing.
6. GitHub: the description length limit and the topic format (lowercase, hyphens, at most
   20 topics).

Anything that differs is a change to this file, the brand script or the repository, made
before the submission is opened, and a line in `docs/decisions-log.md` when it changes a
choice recorded here.
