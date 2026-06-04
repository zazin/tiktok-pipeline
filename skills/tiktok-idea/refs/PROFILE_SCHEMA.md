# Profile schema

A profile makes every generated post the same recurring character: a fixed identity
(reference photos) on a consistent persona, with per-post variety. Profiles live in a
directory you provide (pointed at with `--profiles-dir`, default `profiles/`):

```
profiles/
  <name>/
    profile.json                 # required
    <reference image 1>.jpeg     # files named in reference_images, in this folder
    <reference image 2>.jpeg
```

## profile.json fields

| Field | Type | Required | Purpose |
|---|---|---|---|
| `name` | string | yes | Display name of the character. |
| `gender` | string | no | Demographic, folded into the persona. |
| `generation` | string | no | e.g. "Gen Z" — folded into the persona. |
| `age` | int | no | Folded into the persona. |
| `industry` | string | no | Niche, folded into the persona. |
| `persona` | string | yes | The detailed character description (concept, USP, voice, physical style). |
| `content_pillars` | string[] | no | Recurring content themes, folded into the persona. |
| `variety` | object | no | Pools used to vary each post (see below). Overrides built-in defaults. |
| `variety.outfits` | string[] | no | Outfit phrases. |
| `variety.settings` | string[] | no | Setting/location phrases. |
| `variety.poses` | string[] | no | Pose phrases. |
| `reference_images` | string[] | yes | Filenames (in this folder) of the identity reference photos; each must exist. |
| `reference_kind` | `preserve` \| `feature` | no | How references are used (default `preserve`: keep the subject identical). |

When a persona is present, the idea step describes the **scene / pose / wardrobe**
(not facial features — identity is fixed by the reference images), and a `--seed`
makes the outfit/setting/pose pick reproducible.

## Minimal template

```json
{
  "name": "Aria",
  "gender": "Wanita",
  "generation": "Gen Z",
  "age": 23,
  "industry": "Coffee & Lifestyle",
  "persona": "Aria is a 23-year-old barista and home-cafe enthusiast. CONCEPT: ... USP: ... PHYSICAL: varies outfits across posts ... VOICE: warm, casual, lots of Gen Z slang.",
  "content_pillars": [
    "#HomeCafe — recreating cafe drinks at home on a budget.",
    "#BeanReview — honest reviews of local coffee beans."
  ],
  "variety": {
    "outfits": ["a cream knit sweater", "a denim jacket over a white tee", "an olive utility shirt"],
    "settings": ["in a sunlit home kitchen", "at a wooden cafe counter", "on a balcony in the morning"],
    "poses": ["holding a mug up to the light", "pouring milk into a cup", "an over-the-shoulder glance at the camera"]
  },
  "reference_images": ["aria_portrait.jpeg", "aria_full_body.jpeg"],
  "reference_kind": "preserve"
}
```

Place the two referenced `.jpeg` files alongside `profile.json` in
`profiles/aria/`. Then: `--profile aria --profiles-dir ./profiles`.
