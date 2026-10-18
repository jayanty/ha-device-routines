# Publication

Everything Device Routines needs to be listed in Home Assistant's brands repository and in
the HACS default list, prepared in this repository and opened nowhere. Each outward facing
step is the owner's: the owner does it, or tells a session in chat to do it under his
account (plan Section 6.4). Nothing here has been opened, submitted or changed on GitHub.

| Owner log | Item | Gates |
| --- | --- | --- |
| O10 | Approve the icon and logo; go ahead for the `home-assistant/brands` pull request | The HACS check without `ignore: brands`, and so the HACS default submission |
| O11 | Go ahead for the HACS default submission, including the repository description and topics | Listing in HACS without a custom repository |
| O12 | The console look that gates the `v1.0.0` tag | The release the HACS submission points at |

The texts below are public once opened. They name no real home, device, area, person or
address, only the project, its repository `jayanty/ha-device-routines` and generic
examples.

## Order of the steps

| Step | What | Who | Owner log | When |
| --- | --- | --- | --- | --- |
| 1 | Look at the [brand images](#the-brand-images) and approve them, or say what to change | Owner | O10 | Any time |
| 2 | Open the [brands pull request](#the-brands-pull-request) | Owner, or a session on his go ahead | O10 | After step 1. It needs no release, so it can be opened before `v1.0.0` and should be, because review takes a while |
| 3 | Set the [repository description and topics](#repository-description-and-topics), and check that issues are enabled | Owner, or a session on his go ahead | O11 | Before step 6 |
| 4 | When the brands pull request has merged: remove `ignore: brands` from the `hacs` job of `.github/workflows/ci.yml` (decision L14) and move `brands` in `quality_scale.yaml` to `done`; CI must be green with every HACS check on | Session | O10 | After the merge |
| 5 | Release `v1.0.0` with CI green after step 4. If `v1.0.0` was tagged before the brands merge, release a patch (`v1.0.1`) after step 4 instead, because the HACS submission asks for a release made after the checks passed without anything ignored | Session | O12 | After live validation B and O12 |
| 6 | Open the [HACS default submission](#the-hacs-default-submission) | Owner, or a session on his go ahead | O11 | After steps 3 to 5 |
| 7 | When the submission has merged: switch the README's HACS badge and install steps from custom repository to default (see [After the listing](#after-the-listing)) | Session | O11 | After the merge |

The channel switch of the owner's own instance (O13) is separate and can happen before,
between or after these steps.

## The brand images

`tools/make_brand.py` draws every image; run `.venv/bin/python -m tools.make_brand` to
write them and `.venv/bin/python -m tools.make_brand --check` to compare the committed
files with a fresh drawing. The same bytes sit in two places: `brand/`, which this
repository keeps, and `brand/brands/custom_integrations/device_routines/`, which is the
folder the brands pull request copies as it is.

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
dark backgrounds down to 24 px, so there is no `dark_icon.png`. The words of the logo are
set in Aileron Regular from dotcolon (`https://dotcolon.net/fonts/aileron`), released under
CC0 1.0 (public domain) and bundled with Pillow as its default font, with a light stroke
for a medium weight. The logo is not
the icon alone, so the brands repository's rule against a logo equal to the icon does not
apply.

Every image is a PNG in RGBA with a transparent background, trimmed (something is drawn on
every edge row and column), not interlaced and without metadata. The dark logos are
optional for the brands repository; drop them from the pull request if a reviewer asks.

What proves it, in `tests/test_repository.py`:

| Requirement | Test |
| --- | --- |
| Exactly these files, in both places | `test_the_brand_files_are_exactly_the_drawn_set` |
| PNG, RGBA, transparent corners, not interlaced | `test_every_brand_image_is_an_rgba_png_with_transparent_corners` |
| Trimmed | `test_every_brand_image_is_trimmed` |
| Icons 256 and 512 square | `test_the_icons_are_square_at_256_and_512` |
| Logos landscape, shortest side 128 to 256, @2x exactly double | `test_the_logos_are_landscape_within_the_brands_limits` |
| The brands layout holds the same bytes as `brand/` | `test_the_brands_layout_mirrors_brand` |
| The script draws the committed images, byte for byte | `test_make_brand_draws_the_committed_image_data`, `test_make_brand_reproduces_the_committed_files_byte_for_byte` |

## The brands pull request

Owner log O10. Repository `home-assistant/brands`, one new folder
`custom_integrations/device_routines/`, nothing else changed.

The commands, for the owner or a session on his go ahead (not run):

```bash
REPO=/path/to/this/checkout  # the commit the images were approved on
gh repo fork home-assistant/brands --clone
cd brands
git switch -c add-device-routines
mkdir -p custom_integrations/device_routines
cp "$REPO"/brand/brands/custom_integrations/device_routines/*.png \
  custom_integrations/device_routines/
git add custom_integrations/device_routines
git commit -m "Add Device Routines custom integration"
git push -u origin add-device-routines
gh pr create --repo home-assistant/brands \
  --title "Add Device Routines custom integration (device_routines)" \
  --body-file brands-pr.md
```

`brands-pr.md` is the body below, with the template's own checklist pasted over the one
here if the template has changed.

Title:

```text
Add Device Routines custom integration (device_routines)
```

Body:

```markdown
## Proposed change

Adds the icon and logo of Device Routines, a custom integration for Home Assistant
distributed through HACS. It adds start and stop times, run timers and a plain language
Schedule sentence to device pages, backed by clearly marked automations built from a
blueprint it ships.

- Domain: `device_routines` (no core integration uses it)
- Repository: https://github.com/jayanty/ha-device-routines
- Manifest: https://github.com/jayanty/ha-device-routines/blob/main/custom_components/device_routines/manifest.json

| File | Size |
| --- | --- |
| `icon.png` | 256 x 256 |
| `icon@2x.png` | 512 x 512 |
| `logo.png` | 552 x 128 |
| `logo@2x.png` | 1104 x 256 |
| `dark_logo.png` | 552 x 128 |
| `dark_logo@2x.png` | 1104 x 256 |

The images are the project's own design (a calendar with a clock), drawn for it and
generated by a script in the repository; they use no third party trademark. The words are
set in Aileron Regular, which is CC0. The dark logos change only the color of the words;
the icon reads on both themes, so there is no dark icon.

## Type of change

- [ ] Add a new logo or icon for a new core integration
- [x] Add a new logo or icon for a custom integration
- [ ] Replace an existing logo or icon
- [ ] Remove a logo or icon

## Checklist

- [x] The added images are PNG.
- [x] `icon.png` is 256 x 256 and square.
- [x] `icon@2x.png` is 512 x 512 and square.
- [x] `logo.png` has a shortest side between 128 and 256 (128).
- [x] `logo@2x.png` has a shortest side between 256 and 512 (256).
- [x] The images are trimmed: no transparent padding around what is drawn.
- [x] The images have a transparent background.
- [x] The images are losslessly compressed and carry no metadata.
- [x] The logo differs from the icon (it adds the name).
- [x] The images are not upscaled: every size is drawn at that size.
- [x] The custom integration exists and is installable:
      https://github.com/jayanty/ha-device-routines
```

Before opening, check (step owner):

- [ ] The images were approved under O10.
- [ ] `.venv/bin/python -m tools.make_brand --check` prints nothing on the commit the
      images are copied from.
- [ ] The folder `custom_integrations/device_routines/` does not exist in the brands
      repository yet, and `core_integrations/` has no `device_routines` either.
- [ ] The checklist above still matches the template the brands repository shows when the
      pull request is opened.

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
- [ ] The brands pull request has merged and `ignore: brands` is gone from `ci.yml`.
- [ ] The `hacs` and `hassfest` jobs passed on `main` with nothing ignored, and their runs
      are linked in the body.
- [ ] A full release (not a pre release) with `device_routines.zip` was published after
      those runs: `v1.0.0`, or `v1.0.1` if `v1.0.0` came before the brands merge.
- [ ] `jayanty/ha-device-routines` is not in the list yet.
- [ ] The owner opens it from his own account: HACS asks that the submitter owns or
      maintains the repository.

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
- `quality_scale.yaml`: `brands` is `done` from step 4 on.
- The owner log closes O10 and O11 with the links of the merged pull requests.

## Check against the current upstream rules before opening

This file was written from the documented rules as known when it was prepared, without
reading the upstream pages again. Before opening anything, the owner (or the session on his
go ahead) compares these points with the current `home-assistant/brands` README and pull
request template and the current HACS publishing documentation and `hacs/default`
template:

1. Brands, location: custom integrations still go under
   `custom_integrations/<domain>/`, and the brands repository still takes custom
   integrations at all. Also whether Home Assistant or HACS has since added another way for
   a custom integration to provide its images; if so, follow it instead.
2. Brands, files and sizes: the names `icon.png`, `icon@2x.png`, `logo.png`,
   `logo@2x.png`; icons 256 and 512 square; the shortest side of a logo 128 to 256 and of
   `@2x` 256 to 512; whether `dark_` variants are still accepted and named that way.
3. Brands, image rules: transparent background, how much padding counts as trimmed,
   whether images must be compressed by a particular tool or stay under a file size
   (ours are 8 to 24 KB), and whether interlacing or metadata are refused.
4. Brands, the pull request template's checklist and type of change, and whether one pull
   request may add only one domain.
5. HACS, requirements for the default list: a full release rather than tags or pre
   releases, the description and topics, issues enabled, the brands entry, and the HACS
   and hassfest actions passing without `ignore`.
6. HACS, the submission itself: the file that lists integrations and how it is ordered,
   the title format, the template's checklist and links, and whether the submitter must
   be the repository's owner.
7. HACS, `hacs.json`: that `name`, `render_readme`, `zip_release`, `filename` and
   `homeassistant` are still the keys it reads, and nothing it now requires is missing.
8. GitHub: the description length limit and the topic format (lowercase, hyphens, at most
   20 topics).

Anything that differs is a change to this file, the brand script or the repository, made
before the pull request is opened, and a line in `docs/decisions-log.md` when it changes a
choice recorded here.
