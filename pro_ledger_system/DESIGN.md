---
name: Pro Ledger System
colors:
  surface: '#f8f9fa'
  surface-dim: '#d9dadb'
  surface-bright: '#f8f9fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f4f5'
  surface-container: '#edeeef'
  surface-container-high: '#e7e8e9'
  surface-container-highest: '#e1e3e4'
  on-surface: '#191c1d'
  on-surface-variant: '#434654'
  inverse-surface: '#2e3132'
  inverse-on-surface: '#f0f1f2'
  outline: '#737686'
  outline-variant: '#c3c5d7'
  surface-tint: '#1353d8'
  primary: '#003fb1'
  on-primary: '#ffffff'
  primary-container: '#1a56db'
  on-primary-container: '#d4dcff'
  inverse-primary: '#b5c4ff'
  secondary: '#785900'
  on-secondary: '#ffffff'
  secondary-container: '#fdc003'
  on-secondary-container: '#6c5000'
  tertiary: '#005438'
  on-tertiary: '#ffffff'
  tertiary-container: '#006f4b'
  on-tertiary-container: '#7af3bb'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe1ff'
  primary-fixed-dim: '#b5c4ff'
  on-primary-fixed: '#00174d'
  on-primary-fixed-variant: '#003dab'
  secondary-fixed: '#ffdf9e'
  secondary-fixed-dim: '#fabd00'
  on-secondary-fixed: '#261a00'
  on-secondary-fixed-variant: '#5b4300'
  tertiary-fixed: '#81f9c1'
  tertiary-fixed-dim: '#63dca6'
  on-tertiary-fixed: '#002113'
  on-tertiary-fixed-variant: '#005236'
  background: '#f8f9fa'
  on-background: '#191c1d'
  surface-variant: '#e1e3e4'
typography:
  headline-lg:
    fontFamily: Vazirmatn
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  headline-md:
    fontFamily: Vazirmatn
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Vazirmatn
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Vazirmatn
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-lg:
    fontFamily: Vazirmatn
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  label-sm:
    fontFamily: Vazirmatn
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  headline-lg-mobile:
    fontFamily: Vazirmatn
    fontSize: 22px
    fontWeight: '700'
    lineHeight: 30px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  margin-mobile: 1rem
  gutter-mobile: 0.75rem
  stack-sm: 0.5rem
  stack-md: 1rem
  stack-lg: 1.5rem
---

## Brand & Style
The design system is engineered for an Accounting & Sales environment where precision meets speed. The brand personality is **Professional, Trustworthy, and Efficient**, tailored for business owners who require clarity in their financial data. 

The visual style follows a **Modern Corporate Minimalism** approach. It utilizes expansive white space to reduce cognitive load during complex data entry and emphasizes a Right-to-Left (RTL) first workflow. The interface is characterized by clean lines, high-quality typography, and a "light-first" aesthetic that conveys transparency and organization. It prioritizes functional clarity over decorative elements, ensuring that financial figures are the primary focus.

## Colors
The palette is rooted in a **Professional Blue** (#1A56DB), used for core navigation, primary actions, and branding elements to establish authority. An **Energetic Yellow** (#FFC107) serves as the high-visibility accent for Call-to-Actions (CTAs) and critical status indicators, creating a sharp contrast against the blue.

- **Primary:** Professional Blue for reliability.
- **Secondary/Accent:** Energetic Yellow for urgency and highlights.
- **Success:** Green (#0E9F6E) for positive financial balances and completed sales.
- **Neutral Background:** A soft Light Gray (#F8F9FA) to prevent eye strain and differentiate card surfaces from the canvas.
- **Text:** Deep Navy (#111928) for high legibility, avoiding pure black to maintain a modern feel.

## Typography
This design system utilizes **Vazirmatn** (or Inter as a fallback for Latin characters) to ensure maximum legibility for Persian script and financial numerals. Since accounting requires frequent reading of numbers, the chosen font family provides excellent clarity at small sizes.

The hierarchy is strictly enforced to guide the user through complex sales forms. Headlines use a heavier weight to anchor sections, while body text maintains a generous line height for readability. For RTL layouts, text alignment is always right-justified except for numerical data tables, which may remain left-aligned or centered for standard accounting practices.

## Layout & Spacing
The layout follows a **Fluid Grid** model inspired by Bootstrap's mobile-first philosophy. On mobile devices, a 4-column grid is used with 16px (1rem) side margins and 12px (0.75rem) gutters between elements.

Spacing follows an 8px base unit (4, 8, 16, 24, 32, 48, 64) to maintain a consistent vertical rhythm. Large margins are used between distinct functional blocks (e.g., separating the "Total Balance" card from the "Recent Transactions" list) to preserve the minimal, airy aesthetic.

## Elevation & Depth
Depth is created through **Tonal Layers** and **Ambient Shadows**. Instead of heavy borders, the design system uses subtle surface elevation to define hierarchy.

1.  **Base Layer:** The light gray (#F8F9FA) background serves as the canvas.
2.  **Raised Layer (Cards):** Pure white (#FFFFFF) surfaces with a soft, diffused shadow (0px 4px 12px rgba(0, 0, 0, 0.05)). This makes data containers appear "floated" and tappable.
3.  **Active Layer:** Primary buttons and active input fields use a slight increase in shadow intensity or a 1px solid blue border to indicate focus.

## Shapes
The shape language is consistently **Rounded**, using a 12px (0.75rem) base radius for cards and major UI containers. This softens the "industrial" feel of accounting software, making the app feel more approachable and modern.

- **Small Components (Buttons/Inputs):** 8px corner radius.
- **Medium Components (Cards/Modals):** 12px corner radius.
- **Badges:** Fully pill-shaped (rounded-full) to distinguish them from interactive buttons.

## Components

### Buttons
- **Primary:** Solid Professional Blue with white text. 12px vertical padding.
- **Secondary (CTA):** Solid Energetic Yellow with Deep Navy text for maximum contrast on critical actions like "Confirm Sale."
- **Ghost:** Transparent background with a blue outline for secondary navigation.

### Cards
- White background, 12px rounded corners, and a 5% opacity black shadow. 
- Padding inside cards should be at least 16px to maintain the "generous white space" requirement.

### Input Fields
- Subtle gray background (#F3F4F6) with no border in default state.
- Transition to a 2px blue border on focus.
- RTL alignment: Labels and placeholders right-aligned.

### Chips & Status Badges
- Used for "Paid," "Pending," or "Overdue." 
- Pill-shaped with a low-opacity background tint matching the status color (e.g., Light Green background with Dark Green text for "Paid").

### Lists
- Clean, divider-less lists using white space and subtle horizontal lines (#E5E7EB) to separate items. 
- Icons should be placed on the right (RTL) followed by text labels.