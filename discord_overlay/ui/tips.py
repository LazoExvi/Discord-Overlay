"""OCR accuracy guidance shown on the Tips tab and in the start-up reminder."""

# The five settings that decide accuracy, shown every time the app opens.
ESSENTIAL_TIPS = (
    ("One message per line",
     "Make the combat window wide enough that even the longest line stays on one row. A message that "
     "wraps onto a second line is read as two fragments and its damage can be lost."),
    ("Black, opaque background",
     "Set the combat window background to solid black. Transparency lets the game world bleed through "
     "the letters."),
    ("Readable font, then taller window",
     "Raise the font only until text is crisp; past that, prefer a taller window so lines stay visible "
     "longer before scrolling away."),
    ("Nothing over the text",
     "Keep the mouse pointer, other windows, tooltips, and the timer overlays out of the capture region. "
     "Anything drawn over the chat replaces the letters underneath."),
    ("Select with a margin",
     "When you draw the capture region, leave a small gap around the text and never cut through the "
     "top, bottom, or sides of a line."),
)

ACCURACY_TIPS = (
    "• Use a black, fully opaque combat-window background.\n\n"
    "• Increase the in-game combat font size so OCR can distinguish each character.\n\n"
    "• Make the combat window wider so most or all messages fit on one line.\n\n"
    "• Make the window taller so more lines remain visible between OCR scans.\n\n"
    "• Keep the mouse pointer outside every OCR capture region while monitoring. Hovering over "
    "combat text changes the captured pixels and can reduce accuracy. Discord Overlay repairs words "
    "the cursor hides using recently seen lines, marked with ~ in the Log, but it never guesses "
    "hidden numbers.\n\n"
    "• Leave a small margin around the combat text. Do not cut through the top, bottom, or sides of "
    "letters; include the complete height and width of every line.\n\n"
    "• For the most accurate group numbers, turn on the Group filter in Settings and list every "
    "player and pet name in your group. Fights are then counted only when one side is you or a "
    "listed name, so passers-by fighting nearby are excluded. Mobs do not need to be listed. The "
    "list is saved per character.\n\n"
    "• Reduce unnecessary combat spam when possible. If you do not need them for parsing or "
    "triggers, hide messages such as melee misses so important damage, healing, and mechanic lines "
    "stay visible longer.\n\n"
    "• Accuracy can decrease at higher levels or in a full party because combat spam may scroll out "
    "before it can be read. A taller window and faster scan interval help.\n\n"
    "• Arrange timer overlays outside every OCR capture region. Click-through stops them from "
    "intercepting input, but visible overlay pixels still cover combat text if the windows overlap."
)
