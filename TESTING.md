# Testing Plan for claude-ai-music-skills

Comprehensive testing checklist before marketplace release.

## Codex startup and resume

Install the pinned Codex CLI and use an existing dependency venv:

```bash
npm ci --prefix tests/e2e/codex --no-audit --no-fund
python3 tests/e2e/codex_plugin_discovery_check.py --codex tests/e2e/codex/node_modules/.bin/codex
python3 tests/e2e/codex_session_resume_check.py --codex tests/e2e/codex/node_modules/.bin/codex --venv .venv
```

The session probe creates temporary `HOME` and `CODEX_HOME` directories and a
music-project directory outside the plugin. It links the dependency venv into
that home; on Windows it uses a directory junction. On Windows, use `python`
and append `.cmd` to the Codex executable path above. Supply `--venv` or
`--codex` to choose another installation.

**Expected:** Both probes exit 0. Codex discovers the canonical skill set and
starts the MCP server from the isolated installed copy. Through MCP, the session
probe checks configuration, Codex health, source-verification state, album
progress, and persisted session updates; synthetic album and track files remain
unchanged. CI runs these checks without model turns on Linux and Windows.

To run the optional authenticated model probe:

```bash
python3 tests/e2e/codex_session_resume_check.py --codex tests/e2e/codex/node_modules/.bin/codex --venv .venv --model-check
```

This consumes account usage. When available, the probe temporarily copies the
existing `auth.json` into the isolated Codex home with private permissions.
The startup prompt requests dependency inspection and `configure show` without
installing packages. A passing run requires plugin MCP calls to return usable
JSON without business errors and Codex health to report `ok` or `warn`. The
resume turn must independently query session context, recommend source
verification, and persist a fresh session update.

The automated model probe does not independently prove that every setup or
configuration step ran. It covers this startup/resume workflow, not a fresh
dependency installation or the downstream music-production pipeline.

### Manual conversational acceptance

Use a separate temporary `HOME` and `CODEX_HOME` (`USERPROFILE` as well on
Windows), an installed copy of the plugin, and a music workspace outside the
plugin. Start a new Codex/MCP process in that environment; changing `HOME` in
an existing session does not redirect its already-running MCP server. Use a
synthetic album with at least one track awaiting source verification. If using
a temporary authentication copy, restrict its permissions and remove it after
testing.

1. With no config in the isolated home, invoke `setup` to inspect dependencies,
   then invoke `configure setup` without supplying settings. Expect questions
   for the required fields and no config file until answers are supplied.
2. Provide an artist and content, audio, documents, and overrides paths. Use a
   path containing spaces and an overrides directory outside the content root.
   Expect the saved YAML to preserve the supplied values and artist casing.
   Change only the audio path with `configure edit` and compare the other fields.
3. Place a unique marker in the configured overrides `CLAUDE.md` and a different
   marker in the music workspace's `CLAUDE.md`. Start a fresh `session-start`
   session without revealing the markers. Expect the configured marker, a
   `health_check(runtime="codex")` call, and no cwd marker. With the optional
   overrides directory absent, startup should continue without it.
4. Resume the synthetic album by name and then in a new session without a name.
   Expect the source-verification recommendation and the correct album and
   phase persisted in session state. Missing config should direct the user to
   configure; an unknown album must not create or invent session progress.
5. Compare album and track files before and after startup/resume; expect no
   changes. Record the commit, host, CLI and model settings, tool results,
   retries, and any cases not exercised.

These manual observations are separate from the no-model probe and do not
establish behavior on platforms or workflows that were not exercised.

---

## Prerequisites

- Claude Code installed and working
- Python 3.8+ installed
- Git configured
- A test directory outside the plugin repo (e.g., `~/test-music-plugin/`)

---

## Phase 1: Fresh Install Testing

### 1.1 Clone Install (Primary Method)

```bash
# Create clean test directory
mkdir -p ~/test-music-plugin
cd ~/test-music-plugin

# Clone fresh copy
git clone https://github.com/bitwize-music-studio/claude-ai-music-skills.git
cd claude-ai-music-skills

# Start Claude Code
claude
```

**Verify:**
- [ ] Claude loads without errors
- [ ] CLAUDE.md is recognized (check session start behavior)
- [ ] Skills are available (type `/` and check menu)

### 1.2 Plugin Install (Marketplace Method)

```bash
# In a different directory (not inside the cloned repo)
cd ~/test-music-plugin

# Add marketplace and install
claude
```

Then in Claude Code:
```
/plugin marketplace add bitwize-music-studio/claude-ai-music-skills
/plugin install bitwize-music@claude-ai-music-skills
```

**Verify:**
- [ ] Plugin installs without errors
- [ ] Skills appear in `/` menu
- [ ] Can invoke skills (e.g., `/tutorial help`)

---

## Phase 2: Configuration Testing

### 2.1 Initial Config Setup

```bash
cd ~/test-music-plugin/claude-ai-music-skills

# Copy example config
mkdir -p ~/.bitwize-music
cp config/config.example.yaml ~/.bitwize-music/config.yaml
```

Edit `~/.bitwize-music/config.yaml`:
```yaml
artist:
  name: "test-artist"

paths:
  content_root: "~/test-music-plugin/content"
  audio_root: "~/test-music-plugin/audio"
  documents_root: "~/test-music-plugin/documents"
  tools_root: "~/.bitwize-music"
  plugin_root: "."

urls:
  soundcloud: "https://soundcloud.com/test"

generation:
  service: suno
```

Create directories:
```bash
mkdir -p ~/test-music-plugin/content/artists
mkdir -p ~/test-music-plugin/audio
mkdir -p ~/test-music-plugin/documents
mkdir -p ~/.bitwize-music
```

**Verify:**
- [ ] Config loads on session start
- [ ] No errors about missing paths
- [ ] Claude reports paths correctly

### 2.2 Path Resolution

In Claude Code, ask: "What are my configured paths?"

**Verify:**
- [ ] content_root resolves correctly
- [ ] audio_root resolves correctly
- [ ] documents_root resolves correctly
- [ ] tools_root resolves correctly

---

## Phase 3: Core Workflow Testing

### 3.1 Tutorial Skill

```
/tutorial help
```

**Verify:**
- [ ] Help message displays correctly
- [ ] Shows all three commands (new-album, resume, help)

```
/tutorial resume
```

**Verify:**
- [ ] Scans content_root for albums
- [ ] Reports "no albums found" (expected for fresh install)

### 3.2 Album Creation

```
/tutorial new-album
```

Walk through Phase 1-2 only (Foundation + Concept):
- Artist: "Test Artist" (new)
- Genre: "electronic"
- Album name: "Test Album"
- Type: "Thematic"

**Verify:**
- [ ] Creates artist directory: `{content_root}/artists/test-artist/`
- [ ] Creates album directory: `{content_root}/artists/test-artist/albums/electronic/test-album/`
- [ ] Creates album README.md
- [ ] Creates tracks/ subdirectory

### 3.3 Lyric Writer

Create a test track file, then:
```
/lyric-writer {content_root}/artists/test-artist/albums/electronic/test-album/tracks/01-test-track.md
```

Ask it to write a simple verse.

**Verify:**
- [ ] Skill loads correctly
- [ ] Writes lyrics with section tags
- [ ] Runs automatic review (rhyme, prosody, pronunciation)

### 3.4 Pronunciation Specialist

```
/pronunciation-specialist {content_root}/artists/test-artist/albums/electronic/test-album/tracks/01-test-track.md
```

**Verify:**
- [ ] Scans for pronunciation risks
- [ ] Reports findings (or "no issues" if clean)

### 3.5 Explicit Checker

```
/explicit-checker {content_root}/artists/test-artist/albums/electronic/test-album/
```

**Verify:**
- [ ] Scans all tracks in album
- [ ] Reports explicit content status

### 3.6 Suno Engineer

Ask Claude to help with Suno prompts for a track.

**Verify:**
- [ ] Generates Style Box content
- [ ] Generates Lyrics Box content
- [ ] Uses V5 best practices

---

## Phase 4: Research Workflow Testing

### 4.1 Researcher Skill

```
/researcher "test topic for research"
```

**Verify:**
- [ ] Skill loads correctly
- [ ] Searches for sources
- [ ] Returns formatted results

### 4.2 Document Hunter (Requires Playwright)

First, set up Playwright:
```bash
pip install playwright beautifulsoup4 requests
playwright install chromium
```

Then:
```
/document-hunter "test case name"
```

**Verify:**
- [ ] Creates download directory in documents_root
- [ ] Searches free sources
- [ ] Reports what was found

### 4.3 Document Storage Path

After document-hunter runs:

**Verify:**
- [ ] PDFs saved to `{documents_root}/[artist]/[album]/`
- [ ] manifest.json created alongside PDFs
- [ ] No PDFs in content_root (git-safe)

---

## Phase 5: Mastering Workflow Testing

### 5.1 Shared Venv Setup

```bash
# One-time setup
mkdir -p ~/.bitwize-music
python3 -m venv ~/.bitwize-music/venv
source ~/.bitwize-music/venv/bin/activate
pip install matchering pyloudnorm scipy numpy soundfile
deactivate
```

**Verify:**
- [ ] Venv created successfully
- [ ] All packages install without errors

### 5.2 Mastering Scripts

Create a test folder with a WAV file:
```bash
mkdir -p ~/test-music-plugin/test-master
# Copy any WAV file here for testing
```

```bash
cd ~/test-music-plugin/test-master
source ~/.bitwize-music/venv/bin/activate

# Copy scripts from plugin
cp ~/test-music-plugin/claude-ai-music-skills/tools/mastering/*.py .

# Run analysis
python3 analyze_tracks.py
```

**Verify:**
- [ ] analyze_tracks.py runs without errors
- [ ] LUFS readings displayed

```bash
# Run mastering (dry run first)
python3 master_tracks.py --dry-run

# If dry run OK, run actual mastering
python3 master_tracks.py
```

**Verify:**
- [ ] master_tracks.py runs without errors
- [ ] Creates mastered/ subdirectory
- [ ] Output files at target LUFS (-14)

### 5.3 Audio Output Path

When mastering a real album:

**Verify:**
- [ ] Mastered files go to `{audio_root}/[artist]/[album]/`
- [ ] Album art saved alongside mastered files

---

## Phase 6: Git Safety Testing

### 6.1 PDF Blocking

```bash
cd ~/test-music-plugin/claude-ai-music-skills

# Create a fake PDF in content area
touch ~/test-music-plugin/content/artists/test-artist/test.pdf

# Try to add it
cd ~/test-music-plugin/content
git init  # if not already a repo
git add .
git status
```

**Verify:**
- [ ] PDF is NOT staged (blocked by .gitignore)

### 6.2 Primary Sources Blocking

```bash
mkdir -p ~/test-music-plugin/content/artists/test-artist/albums/electronic/test-album/primary-sources
touch ~/test-music-plugin/content/artists/test-artist/albums/electronic/test-album/primary-sources/doc.pdf

git add .
git status
```

**Verify:**
- [ ] primary-sources/ directory is NOT staged

---

## Phase 7: Skill Inventory Check

Run each skill and verify it loads:

| Skill | Command | Works |
|-------|---------|-------|
| tutorial | `/tutorial help` | [ ] |
| lyric-writer | `/lyric-writer --help` | [ ] |
| album-conceptualizer | (invoke during album creation) | [ ] |
| suno-engineer | (invoke during track work) | [ ] |
| pronunciation-specialist | `/pronunciation-specialist [file]` | [ ] |
| lyric-reviewer | `/lyric-reviewer [file]` | [ ] |
| explicit-checker | `/explicit-checker [album]` | [ ] |
| album-art-director | (invoke during art creation) | [ ] |
| mastering-engineer | (invoke during mastering) | [ ] |
| release-director | (invoke during release) | [ ] |
| researcher | `/researcher "topic"` | [ ] |
| document-hunter | `/document-hunter "case"` | [ ] |
| researchers:legal | `/researchers:legal "case"` | [ ] |
| researchers:gov | `/researchers:gov "topic"` | [ ] |
| researchers:journalism | `/researchers:journalism "topic"` | [ ] |
| researchers:tech | `/researchers:tech "topic"` | [ ] |
| researchers:security | `/researchers:security "topic"` | [ ] |
| researchers:financial | `/researchers:financial "topic"` | [ ] |
| researchers:historical | `/researchers:historical "topic"` | [ ] |
| researchers:biographical | `/researchers:biographical "person"` | [ ] |
| researchers:primary-source | `/researchers:primary-source "subject"` | [ ] |
| researchers:verifier | `/researchers:verifier [album]` | [ ] |
| skill-model-updater | `/skill-model-updater check` | [ ] |

---

## Phase 8: Edge Cases

### 8.1 Missing Config

```bash
# Remove config
rm ~/.bitwize-music/config.yaml

# Start Claude Code
claude
```

**Verify:**
- [ ] Claude prompts user to set up config
- [ ] Doesn't crash or error out

### 8.2 Invalid Paths

Edit paths.yaml with non-existent path:
```yaml
paths:
  content_root: "/nonexistent/path"
```

**Verify:**
- [ ] Claude handles gracefully
- [ ] Offers to create directory or warns user

### 8.3 Empty Album

Create album structure with no tracks:
```bash
mkdir -p ~/test-music-plugin/content/artists/test-artist/albums/electronic/empty-album/tracks
```

Run `/tutorial resume`

**Verify:**
- [ ] Detects album correctly
- [ ] Reports 0 tracks

---

## Phase 9: End-to-End Workflow

Complete one full album cycle (abbreviated):

1. [ ] `/tutorial new-album` - Create album concept
2. [ ] Write 2 test tracks with `/lyric-writer`
3. [ ] Run `/pronunciation-specialist` on both tracks
4. [ ] Run `/lyric-reviewer` on both tracks
5. [ ] Run `/explicit-checker` on album
6. [ ] (Simulate) Mark tracks as Generated
7. [ ] Run mastering on test WAVs
8. [ ] Verify output in `{audio_root}/[artist]/[album]/`

---

## Phase 10: Cleanup

After testing:

```bash
# Remove test directories
rm -rf ~/test-music-plugin/content
rm -rf ~/test-music-plugin/audio
rm -rf ~/test-music-plugin/documents

# Optionally remove shared venv (or keep for future use)
# rm -rf ~/.bitwize-music

# Remove test plugin install
# /plugin uninstall bitwize-music@claude-ai-music-skills
```

---

## Release Checklist

Before publishing:

- [ ] All Phase 1-9 tests pass
- [ ] No error messages during normal operation
- [ ] All 23 skills load correctly
- [ ] Documentation matches actual behavior
- [ ] .gitignore blocks sensitive files
- [ ] Example configs are complete and commented

---

## Quick Test Script

For rapid re-testing, run this sequence:

```bash
#!/bin/bash
# quick-test.sh

set -e

echo "=== Testing Plugin ==="

# Setup
cd ~/test-music-plugin/claude-ai-music-skills
mkdir -p ~/.bitwize-music
cp config/config.example.yaml ~/.bitwize-music/config.yaml

# Create test paths
mkdir -p ~/test-music-plugin/{content/artists,audio,documents}

# Test mastering venv
source ~/.bitwize-music/venv/bin/activate
python -c "import matchering, pyloudnorm, scipy, numpy, soundfile; print('Packages OK')"
deactivate

echo "=== Basic tests passed ==="
echo "Now run 'claude' and test skills manually"
```

---

## Reporting Issues

If tests fail:
1. Note the exact command/action that failed
2. Capture error message
3. Check which phase failed
4. Report at: https://github.com/bitwize-music-studio/claude-ai-music-skills/issues
