# Design system

A clinic's front desk is a loud, fast, interrupted place. Somebody is on the phone, three people are waiting, and the receptionist has about four seconds to find a patient. The interface has to survive that.

So the design goal is not "looks nice in a screenshot". It is: readable at a glance, obvious where to click, and calm enough to use for nine hours straight.

## What this should not look like

The default look of a generated dashboard is well known by now — a purple-to-blue gradient header, evenly spaced white cards with identical shadows, Inter at three weights, emoji standing in for icons, and everything floating in the middle of a page with nothing anchoring it.

We are not building that. Concretely:

- No gradient heroes, no glassmorphism, no frosted panels
- No emoji as iconography — Lucide, sized and aligned deliberately
- Not every surface is a card with the same radius and shadow
- Density varies by purpose: a patient table is dense, a consultation form is not
- Colour carries meaning; it is not decoration sprinkled evenly

## Palette

The identity is **deep ink and marigold**. Navy carries the weight and reads as clinical and trustworthy; marigold is warm, human, unmistakably Indian in feel, and — practically — it is the colour the eye finds fastest on a waiting-room screen.

### Brand

```
Ink        50  #F2F5F8    the lightest wash, page background tint
          100  #DCE5EE
          200  #C7D3E0
          300  #9DAFC4
          400  #6B83A0
          500  #456080
          600  #2E4763
          700  #1F3450    primary actions, sidebar
          800  #15304A
          900  #0E2135    darkest text on light
          950  #080F1A

Marigold   50  #FEF8EC
          100  #FCEBC8
          200  #F8D690
          300  #F2BC58
          400  #E9A23B    accent, active queue token, focus ring
          500  #D4842A
          600  #B0651C
          700  #8A4C18
```

### Neutrals

Warm stone, not cool grey. Cool greys next to navy read as cheap and screen-like; warm neutrals make long sessions easier.

```
Stone      50  #FAF8F5    app background (light)
          100  #F2EFEA
          200  #E5E0D8
          300  #CFC8BC
          400  #A39A8B
          500  #7A7263
          600  #5A5347
          700  #403A31
          800  #2A251F
          900  #16130F

Dark mode surfaces
          bg   #11151A
          raised #171D24
          border #242C36
```

### Status

Every clinical and operational state gets one colour, used consistently everywhere it appears. These are chosen to stay distinguishable under the common forms of colour blindness, and they are never the only signal — each pairs with an icon and a label.

```
Scheduled     Ink 400      #6B83A0    booked, nothing happening yet
Confirmed     Sky          #3C7DA6    patient acknowledged
Waiting       Marigold 400 #E9A23B    checked in, in the queue
Consulting    Teal         #2F7D8C    with the doctor now
Completed     Green        #3E8E5A    done
Cancelled     Stone 400    #A39A8B    deliberately muted, it is a non-event
No-show       Clay         #C1503F    the one that costs the clinic money
Urgent        Clay 600     #A13B2C    priority queue entries
```

Clay rather than pure red. Red is reserved for destructive confirmation — deleting, voiding, suspending — so it keeps its force.

### Semantic tokens

Components reference roles, never raw hex. Every token is defined for both themes, so dark mode is a token swap rather than a parallel stylesheet.

```
--surface            --surface-raised     --surface-sunken
--border             --border-strong
--text               --text-muted         --text-subtle
--primary            --primary-fg         --primary-hover
--accent             --accent-fg
--focus-ring
--status-{state}     --status-{state}-bg
```

## Typography

**IBM Plex Sans** for the interface. It is humanist rather than geometric, so it has warmth Inter does not, and it is clearly not the default choice everyone reaches for. It is also genuinely well drawn at small sizes, which matters in a dense table.

**IBM Plex Mono** for anything that is an identifier or a quantity: patient numbers, invoice numbers, queue tokens, money, vitals. Fixed-width digits mean a column of amounts lines up and can be scanned vertically.

Tabular figures are switched on wherever numbers sit in a column:

```css
font-variant-numeric: tabular-nums;
```

### Scale

A small scale, used strictly. Most interfaces look untidy because they have eleven text sizes.

```
Display   32px / 1.15  600    page titles only
Heading   24px / 1.25  600    section headings
Subhead   18px / 1.35  600    card titles
Body      15px / 1.55  400    default
Small     13px / 1.5   400    supporting text, table cells
Caption   12px / 1.4   500    labels, uppercase with tracking
Token     40px / 1     600    mono, the queue number
```

Base is 15px rather than 16px. In a dense operational tool it buys a meaningful amount of information per screen without hurting readability — and everything scales cleanly to 200% zoom.

## Spacing and shape

4px base unit; the usable steps are 4, 8, 12, 16, 24, 32, 48, 64.

Radius is small and consistent: 6px for inputs and buttons, 10px for cards and dialogs, full for pills and avatars. Nothing is a 24px-radius blob.

Elevation is mostly borders rather than shadows. A 1px warm border reads as crisp; four levels of blurred shadow read as generated. Shadows appear only where something genuinely floats — dropdowns, popovers, dialogs, toasts.

## Motion

Fast, and it means something.

```
instant   100ms   hover, focus, colour change
quick     160ms   dropdowns, tooltips, toggles
smooth    220ms   dialogs, drawers, sheets
ease      cubic-bezier(0.32, 0.72, 0, 1)
```

Nothing animates longer than 250ms. On a screen someone uses hundreds of times a day, animation is latency.

Motion used deliberately:

- A queue token being called gets one attention pulse, then settles
- Numbers on the dashboard count up once on load, never on refetch
- Row actions fade in on hover rather than sitting there permanently
- Saving shows progress in the button itself, not a blocking overlay
- Optimistic updates land instantly and reconcile quietly

`prefers-reduced-motion` removes movement entirely and keeps colour and opacity changes, so nothing becomes unusable.

## Density

Three modes, applied by context rather than by user preference:

- **Dense** — patient lists, appointment lists, audit logs. 36px rows, small text, no wasted padding. The receptionist is scanning.
- **Comfortable** — dashboard, settings, profile. 48px rows, room to breathe.
- **Focused** — consultation workspace, prescription builder. Wide line length, generous spacing, minimal chrome. The doctor is thinking, not scanning.

The consultation screen is the one place where slowing down is correct.

## Layout

Desktop is a fixed sidebar and a fluid content column capped at 1440px, left-aligned rather than centred — a centred dashboard on a wide monitor wastes the left third and pulls the eye to the wrong place.

Tablet collapses the sidebar to icons at 1024px. The consultation screen is designed for this width specifically, since that is what a doctor actually holds.

Mobile gets a bottom navigation bar with the four things a phone is used for — queue, appointments, patients, search — not a hamburger hiding the desktop menu. Tables become card lists. This is a different layout, not a squeezed one.

## Screens that carry the product

Three screens decide whether this feels designed or assembled. They get disproportionate attention.

**The queue** is the one that gets projected on a wall. Large mono tokens, a single clearly-marked "now consulting" row, status by colour and icon, and enough contrast to read from across a room. Almost no chrome.

**The consultation workspace** is where a doctor spends their day. Patient context pinned at the top, history reachable without navigating away, vitals and notes in one scroll, and a save that never loses work. Keyboard-first.

**The patient timeline** is the feature that makes the product feel connected. A real vertical timeline with typed entries — consultation, prescription, lab, invoice — each expandable in place. Not a table with a date column.

## Required states

Every screen that loads data ships four states, and they are built together rather than retrofitted.

**Loading** — skeletons matching the real layout's shape, never a centred spinner.

**Empty** — an explanation and one clear action:

> **No patients yet**
> Register your first patient to start managing appointments and consultations.
> `[ Add patient ]`

Empty because a filter matched nothing is a different state from empty because nothing exists, and says so.

**Error** — plain language, what to do, and a retry. Never a status code.

**Success** — a toast for background actions, inline confirmation for form saves, and optimistic feedback where the outcome is near-certain.

## Accessibility

Targeting WCAG 2.2 AA, checked continuously rather than audited at the end.

- Body text at 4.5:1, large text and UI boundaries at 3:1. The palette was chosen against these ratios, not adjusted afterwards.
- Visible focus everywhere — a 2px marigold ring with offset, which survives on both light and dark surfaces.
- Full keyboard operation. Dialogs trap focus and restore it on close. Tables are arrow-navigable.
- Semantic HTML first, ARIA only where the platform has no equivalent.
- Live regions announce queue changes and save confirmations to screen readers.
- Colour is never the only carrier of state.
- Usable at 200% zoom and at 320px width without horizontal scroll.
- Every input has a real label. Placeholder text is not a label.

## Component base

shadcn/ui on Radix, with tokens replaced by the palette above. Radix handles the accessibility primitives — focus management, dismissal, ARIA wiring — which are easy to get subtly wrong by hand.

shadcn defaults are a starting point, not the finished look. Buttons, inputs, tables, badges and dialogs get restyled to the tokens here before any feature is built on them, so the product does not ship looking like the library's demo.
