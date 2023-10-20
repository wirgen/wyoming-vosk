# Wyoming Vosk

[Wyoming protocol](https://github.com/rhasspy/wyoming) server for the [vosk](https://alphacephei.com/vosk) speech to text system.

This speech-to-text system can run well, even on a Raspberry Pi 3. Using the corrected or limited modes (described below), you can achieve very high accuracy by restricting the sentences that can be spoken.

## Modes

There are three operating modes:

1. Open-ended - any sentence can be spoken, but recognition is very poor compared to [Whisper](https://github.com/rhasspy/wyoming-faster-whisper)
2. Corrected - sentences similar to [templates](#sentence-templates) are forced to match
3. Limited -  only sentences from [templates](#sentence-templates) can be spoken


### Open-ended

This is the default mode: transcripts from [vosk](https://alphacephei.com/vosk) are used directly.

Recognition is very poor compared to [Whisper](https://github.com/rhasspy/wyoming-faster-whisper) unless you use one of the [larger models](https://alphacephei.com/vosk/models).
To use a specific model, such as `vosk-model-en-us-0.21` (1.6GB):

1. Download and extract the model to a directory (`<DATA_DIR>`) so that you have `<DATA_DIR>/vosk-model-en-us-0.21`
2. Run `wyoming_vosk` with `--data-dir <DATA_DIR>` and `--model-for-language en vosk-model-en-us-0.21`

Note that `wyoming_vosk` will only automatically download models listed in `download.py`.


### Corrected

Create your [sentence templates](#sentence-templates) and save them to a file named `<SENTENCES_DIR>/<LANGUAGE>.yaml` where `<LANGUAGE>` is one of the [supported language codes](#supported-languages). For example, English sentences should be saved in `<SENTENCES_DIR>/en.yaml`.

Then, run `wyoming_vosk` like:

``` sh
script/run ... --sentences-dir <SENTENCES_DIR> --correct-sentences <CUTOFF>
```

where `<CUTOFF>` is:

* empty or 0 - force transcript to be one of the template sentences
* 1-100 - allow more sentences that are not similar to templates to pass through

When `<CUTOFF>` is 100, speech recognition is effectively open-ended again. Experiment with different values to find one that lets you speak sentences outside your templates without sacrificing accuracy too much.


### Limited

Follow the instructions for [corrected mode](#corrected), then run `wyoming_vosk` like:

``` sh
script/run ... --sentences-dir <SENTENCES_DIR> --correct-sentences --limit-sentences
```

This will tell vosk that **only** the sentences from you templates can ever be spoken. Sentence correction is still needed (due to how vosk works internally), but it will ensure that sentences outside the templates cannot be sent.

This mode will get you the highest possible accuracy, with the trade-off being that you cannot speak sentences outside the templates.

## Sentence Templates

Each language may have a YAML file with [sentence templates](https://github.com/home-assistant/hassil#sentence-templates).
Most syntax is supported, including:

* Optional words, surrounded with `[square brackets]`
* Alternative words, `(surrounded|with|parens)`
* Lists of values, referenced by `{name}`
* Expansion rules, inserted by `<name>`

The general format of a language's YAML file is:

``` yaml
sentences:
  - this is a plain sentence
  - this is a sentence with a {list} and a <rule>
lists:
  list:
    - value 1
    - value 2
expansion_rules:
  rule: body of the rule
```

Sentences have a special `in/out` form as well, which lets you say one thing (`in`) but put something else in the transcript (`out`).

For example:

``` yaml
sentences:
  - in: lumos
    out: turn on all the lights
  - in: nox
    out: turn off all the lights
```

lets you say "lumos" to send "turn on all the lights", and "nox" to send "turn off all the lights".

The `in` key can also take a list of sentences, all of them outputting the same `out` string.

### Lists

Lists are useful when you many possible words/phrases in a sentence.

For example:

``` yaml
sentences:
  - set light to {color}
lists:
  color:
    - red
    - green
    - blue
    - orange
    - yellow
    - purple
```

lets you set a light to one of six colors.

This could also be written as `set light to (red|green|blue|orange|yellow|purple)`, but the list is more manageable and can be shared between sentences.

List values have a special `in/out` form that lets you say one thing (`in`) but put something else in the transcript (`out`).

For example:

``` yaml
sentences:
  - turn (on|off) {device}
lists:
  device:
    - in: tv
      out: living room tv
    - in: light
      out: bedroom room light
```

lets you say "turn on tv" to turn on the living room TV, and "turn off light" to turn off the bedroom light.

### Expansion Rules

Repeated parts of a sentence template can be abstracted into an expansion rule.

For example:

``` yaml
sentences:
  - turn on <the> light
  - turn off <the> light
expansion_rules:
  the: [the|my]
```

lets you say "turn on light" or "turn off my light" without having to repeat the optional part.

## Supported Languages

* Arabic (`ar`)
* Breton (`br`)
* Catalan (`ca`)
* Czech (`cz`)
* German (`de`)
* English (`en`)
* Esperanto (`eo`)
* Spanish (`es`)
* Persian (`fa`)
* French (`fr`)
* Hindi (`hi`)
* Italian (`it`)
* Japanese (`ja`)
* Korean (`ko`)
* Kazakh (`kz`)
* Dutch (`nl`)
* Polish (`pl`)
* Portuguese (`pt`)
* Russian (`ru`)
* Swedish (`sv`)
* Tagalog (`tl`)
* Ukrainian (`uk`)
* Uzbek (`uz`)
* Vietnamese (`vn`)
* Chinese (`zh`)
