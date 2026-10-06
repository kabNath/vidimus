# Demo assets

`demo.svg` is a static animated SVG that GitHub renders natively in the project README. No tooling required.

`demo.tape` is a script for [VHS](https://github.com/charmbracelet/vhs) that regenerates `demo.gif` reproducibly. If you want a GIF instead of the SVG, install VHS and run:

```bash
brew install vhs                       # macOS
# or
go install github.com/charmbracelet/vhs@latest

vhs demo/demo.tape                     # outputs demo/demo.gif
```

Then commit the GIF and swap the image reference in the root `README.md` accordingly.
