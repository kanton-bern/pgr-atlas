# Glossary

The domain terms of PGR-Atlas. They stay German in the code, the docs and the German UI
(AGENTS.md, Conventions); this page explains each one in English. The French UI's term is in
`app/texts.toml`.

| Term | Meaning |
|---|---|
| **Anriss** (plural Anrisse) | A release area: a circle where a simulated hillslope debris flow (Hangmure) can start, with its centre (`x_anriss`, `y_anriss`) and its area class `A`. Each has an ID, `id_anriss`. The Simulierte Ereignisse map draws the Anrisse as circles; the Anriss view shows one of them |
| **Prozessquelle** (plural Prozessquellen) | A process source: the area within which Anrisse lie (`id_prozessquelle`). Its probabilities and rates feed the probabilistic weighting of its Anrisse. The maps can show the Prozessquellen as a layer |
| **Scenario** | One set of model parameters for an Anriss: area class `A`, release thickness `h` (Anrissmächtigkeit, in cm) and the friction parameters `μ`, `ξ` and `τ₀`. Every scenario is one simulation |
| **Kachel** (plural Kacheln) | A 1 km × 1 km tile of the LV95 grid, the unit the data are stored and fetched by. Its ID is `id_kachel = floor(x / 1000) * 10000 + floor(y / 1000)`. The map layer "Berechnete Kacheln" shows the Kacheln with finished results |
| **LV95 5 m grid** | Every raster uses the Swiss LV95 coordinate system (EPSG:2056) with 5 m × 5 m pixels. Pixel centres lie at `k * 5 + 2.5` m, pixel edges at round multiples of 5 m |
| **IFK** | Intensitäts-Frequenz-Kurve, an intensity-frequency curve: for a pixel or an area, how often a flow reaches at least a given Fliesstiefe (depth), Fliessgeschwindigkeit (velocity) or Druck (pressure). Calculated on demand in the IFK-Berechnung view |
| **Return period** (Wiederkehrperiode) | `1 / p_exceedance`: the mean number of years between two events that reach at least the given intensity |
| **Umhüllende** | The envelope of an Anriss: the outline around every pixel any of its scenarios reaches. Shown in the Anriss view and downloadable |
| **Derivate** | Pre-calculated rasters for the whole canton (for example return periods and intensities), produced by the simulation pipeline from the gold data. The Raster-Derivate view offers them for download |
| **Gebäudeschatten** | A second simulation campaign in which the flows start at building footprints instead of Anrisse: which areas a flow starting at a building reaches, and which other buildings it affects. Shown in the Gebäudeschatten view |
| **Experten-Modus** | A beta mode in IFK-Berechnung and Raster-Karten (ad hoc) that overrides the probabilities for the current session only. Its results are marked as not official, and the IFK charts keep the standard curve as a grey "Original" line |
| **Gold**, **Silver** | Layers of the data lake the pipeline fills. Silver holds the raw simulation output; gold holds it ordered by Kachel and by Anriss, the form the app reads (`Data-Lake-Gold/` in the bucket) |
