---
name: Phosphor Hound OS
colors:
  surface: '#17120e'
  surface-dim: '#17120e'
  surface-bright: '#3e3833'
  surface-container-lowest: '#120d09'
  surface-container-low: '#201b16'
  surface-container: '#241f1a'
  surface-container-high: '#2f2924'
  surface-container-highest: '#3a342f'
  on-surface: '#ece0d9'
  on-surface-variant: '#b9ccb5'
  inverse-surface: '#ece0d9'
  inverse-on-surface: '#352f2b'
  outline: '#849581'
  outline-variant: '#3b4b3a'
  surface-tint: '#00e55b'
  primary: '#edffe8'
  on-primary: '#003911'
  primary-container: '#00ff66'
  on-primary-container: '#007128'
  inverse-primary: '#006e27'
  secondary: '#ffb86c'
  on-secondary: '#492900'
  secondary-container: '#ed9000'
  on-secondary-container: '#583200'
  tertiary: '#f4ffd4'
  on-tertiary: '#263502'
  tertiary-container: '#d0e69f'
  on-tertiary-container: '#56682e'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#6bff83'
  primary-fixed-dim: '#00e55b'
  on-primary-fixed: '#002107'
  on-primary-fixed-variant: '#00531b'
  secondary-fixed: '#ffdcbc'
  secondary-fixed-dim: '#ffb86c'
  on-secondary-fixed: '#2c1600'
  on-secondary-fixed-variant: '#683c00'
  tertiary-fixed: '#d5eba4'
  tertiary-fixed-dim: '#bacf8a'
  on-tertiary-fixed: '#141f00'
  on-tertiary-fixed-variant: '#3c4c16'
  background: '#17120e'
  on-background: '#ece0d9'
  surface-variant: '#3a342f'
typography:
  headline-xl:
    fontFamily: Space Mono
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.04em
  headline-xl-mobile:
    fontFamily: Space Mono
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
    letterSpacing: -0.03em
  headline-lg:
    fontFamily: Space Mono
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 38px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Space Mono
    fontSize: 22px
    fontWeight: '700'
    lineHeight: 28px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Space Mono
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 28px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: JetBrains Mono
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  body-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0.01em
  label-lg:
    fontFamily: Space Mono
    fontSize: 13px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.08em
  label-md:
    fontFamily: Space Mono
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.1em
  label-sm:
    fontFamily: Space Mono
    fontSize: 9px
    fontWeight: '700'
    lineHeight: 12px
    letterSpacing: 0.12em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-tablet: 2rem
  margin-desktop: 3rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system synthesizes late-1970s analog desktop hardware with 1980s green/amber CRT phosphor terminals and a tongue-in-cheek "retro cyber-dog operative" AI console narrative. The aesthetic is tactile, utilitarian, and playfully self-serious: imagine an elite canine espionage telecommunications unit run on mainframe hardware, woodgrain-framed monitors, and terminal command interfaces.

Visually, the style combines:
- **Analog Warm Brutalism & Phosphor Luminescence:** Deep espresso roast and charcoal-baked CRT chassis backgrounds serve as the ground for dual phosphor emitters: blazing Matrix emerald (`#39FF14` / `#00FF66`) and warm 70s aviator amber (`#FF9E1B` / `#FFB800`).
- **Tactile Terminal Realism:** CRT raster scanlines (`repeating-linear-gradient`), subtle screen-glow blooms, monospaced ASCII telemetry brackets, and hardware-style prompt characters (`❖`, `➔`, `[✕]`, `▲`, `::`).
- **High-Contrast Playfulness:** Crisp pixel borders, chunky physical keycap button states, glowing pill badges, and serious technical telemetry balanced with offbeat retro-futuristic dog-operator iconography.

## Colors

The color palette is built on high-contrast CRT emission physics against an aged analog housing.

- **Primary (`#00FF66` / Phosphor Green):** Represents active terminal transmission, code execution, valid diagnostic signals, and primary command vectors. Emits a neon drop-glow on interactive triggers.
- **Secondary (`#FF9E1B` / Amber Aviator):** Directly inspired by retro 70s tinted glasses and vintage amber tube monocles. Used for system alerts, operational switches, warnings, highlighted prompts, and key telemetry tags.
- **Tertiary (`#8FA363` / Rotary Olive):** Echoes vintage telecommunications receivers and retro olive military hardware. Ideal for secondary metadata, subdued indicators, telemetry readouts, and hardware divider borders.
- **Neutral Base (`#191410` / Dark Roasted Espresso CRT):** A rich, organic dark-brown black instead of pure cold slate. Surrounding surfaces lift to `#271F19` (Console Bezel) and `#382B21` (Tactile Card Surface).
- **Subdued Phosphor (`#4E6B47` & `#8C6533`):** De-energized phosphor traces used for inactive borders, placeholder text, and muted gridlines.

## Typography

Typography prioritizes terminal legibility, rigid monospace alignment, and nostalgic mainframe character.

- **Display & Headline Hierarchy:** Handled by **Space Mono**. Headings are uppercase or lead with system glyphs (`❖ [SYS.INIT]`, `▲ OPERATOR_OVERRIDE`). Tight letter-spacing keeps titles compact and punchy.
- **Body & Data Streams:** Handled by **JetBrains Mono**. Offers unmatched readability for console logs, nested code, hex addresses, tabular canine telemetry, and conversational agent output.
- **Labels & System Chips:** Set strictly in **Space Mono** bold with wide letter tracking (`0.08em - 0.12em`) and full uppercase formatting to mimic stamped hardware faceplates and tape cartridge labels.

## Layout & Spacing

The layout is constructed around an instrument-panel chassis metaphor. Every screen section feels like an isolated hardware bay or cathode module.

- **Grid Architecture:** Desktop views operate on a modular 12-column grid or an asymmetric mainframe split-deck (e.g., 4-column telemetry sidebar + 8-column primary prompt stream). Mobile collapses sequentially into stacked CRT panels.
- **Rhythm & Padding:** Spacing follows strict multiples of `4px` / `8px` (`space-xs` = 4px, `space-sm` = 8px, `space-md` = 16px, `space-lg` = 24px, `space-xl` = 40px). Interior padding in terminal cards is kept snug (`12px` to `16px`) to reinforce technical density.
- **Scanline Overlay:** Top-level containers may feature a persistent, non-blocking CSS scanline gradient layer (`rgba(0, 0, 0, 0.2)` on alternating 2px horizontal bands) to preserve the phosphor illusion.

## Elevation & Depth

This design system rejects generic blurred drop shadows in favor of **phosphor tube illumination** and **beveled mechanical layering**.

1. **Base Deck (Level 0):** Deep espresso chassis background (`#191410`). Non-interactive, grounding layer.
2. **Terminal Bays (Level 1):** Slightly elevated CRT viewport panels (`#271F19`) framed by a 1px or 2px crisp border (`#4E382A` or `#8FA363`). Subtle inner shadow (`inset 0 0 12px rgba(0, 0, 0, 0.7)`) to mimic the curved bevel of glass tube monitors.
3. **Active Terminal Elements (Level 2):** Focused inputs, modal panels, and running pods (`#382B21`) outlined in sharp primary phosphor (`#00FF66`).
4. **Phosphor Glow:** Interactive active states employ neon outer halos instead of grey drop shadows:
   - Green Glow: `0 0 8px rgba(0, 255, 102, 0.45), 0 0 16px rgba(0, 255, 102, 0.2)`
   - Amber Glow: `0 0 8px rgba(255, 158, 27, 0.45), 0 0 16px rgba(255, 158, 27, 0.2)`
5. **Physical Keypress Depth:** Buttons use hard offset shadows (`0 3px 0 #120E0B`) that depress on active click (`translateY(2px)`, shadow reduced to `0 1px 0`).

## Shapes

The shape language reflects classic early-generation computer casings: predominantly squared edges with soft, micro-beveled corners (`4px` / `roundedness: 1`) to emulate molded plastic and phenolic resin console equipment. 

The sole exception to the angular baseline is the **Glowing Pill Badge**: dynamic status indicators, operational chips, and telemetry tags use full-radius pill silhouettes (`9999px`) to create an authentic contrast against the rigid terminal boxes and grid geometry.

## Components

### 1. Buttons & Triggers
- **Primary Terminal Button:** Emerald background (`#00FF66`) with charcoal text (`#191410`), uppercase monospace font, and a 2px offset solid drop border. On hover, displays an emerald phosphor halo (`box-shadow: 0 0 12px rgba(0,255,102,0.6)`).
- **Amber Interrupt Button:** Amber background (`#FF9E1B`) with dark text, prefixed with system glyphs like `▲ ABORT` or `❖ ENGAGE`.
- **Ghost/Keycap Secondary:** Dark chassis fill (`#271F19`), 1px olive border (`#8FA363`), phosphor green text. On click, translates down 2px.

### 2. Glowing Pill Badges & Chips
- Status indicators styled as elongated pills (`border-radius: 9999px`), 1px phosphor outline, translucent colored background (`rgba(0, 255, 102, 0.1)`), and leading pulsing terminal bullets (`● ONLINE`, `▲ BUSY`, `[✕] DISCONNECTED`).

### 3. Terminal Prompt Input & Command Bars
- Dark CRT recess (`#120E0B`) with an inset border.
- Leading persistent shell prefix: `CANINE-AGENT-07::root$ ➔` in amber (`#FF9E1B`), followed by a glowing phosphor-green block cursor (`█`) that blinks at 1Hz (`animation: blink 1s step-end infinite`).
- Text input directly renders in emerald phosphor JetBrains Mono.

### 4. Cards & Console Pods
- Framed in 1px to 2px retro hardware borders (`#4E382A` or `#8FA363`).
- Cards feature an integrated header banner bar displaying hardware serial metadata (e.g., `// TELEM_FRAME_v2.4 ❖ DOG_SYS [ACTIVE]`).
- Optional subtle dot-matrix or CRT scanline background pattern.

### 5. Checkboxes & Radio Toggles
- Custom monospaced glyph controls: unselected rendered as bracketed space `[ ]`, selected rendered as `[✕]` or `[■]` in neon green.
- Radio buttons styled as analog rocker toggles or `(●)` phosphor nodes.

### 6. Lists & Log Feeds
- Structured as timestamped terminal records (`[14:02:18.044] ➔ AUDIO_TAP_INITIALIZED`). Alternating subtle zebra striping with transparent dark-espresso bands.
- Log levels highlighted with colorized bracket stamps (`[INFO]` in tertiary olive, `[WARN]` in amber, `[CRIT]` in phosphor green inverted).