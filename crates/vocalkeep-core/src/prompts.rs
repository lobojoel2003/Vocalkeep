//! Prompt sets: the sentences people read aloud.
//!
//! Sets live in `shared/prompts/*.json` and are compiled into the app. Each prompt can carry its
//! eSpeak NG phonemes (`ph`), added by `scripts/annotate_prompts.py`, which lets the progress view
//! show how many of the language's sounds and sound pairs have been recorded.

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use serde::{Deserialize, Serialize};

/// One sentence to read.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Prompt {
    pub id: String,
    pub text: String,
    /// eSpeak NG phonemes: words separated by spaces, phonemes by `_`, stress marks removed.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ph: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PromptSet {
    pub id: String,
    pub language: String,
    pub title: String,
    pub description: String,
    pub license: String,
    pub source: String,
    #[serde(default)]
    pub attribution: Option<String>,
    pub prompts: Vec<Prompt>,
}

/// A summary of a set for the UI (without the prompts).
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptSetInfo {
    pub id: String,
    pub language: String,
    pub title: String,
    pub description: String,
    pub license: String,
    pub source: String,
    pub attribution: Option<String>,
    pub count: usize,
    /// How often this set is chosen relative to the others in a balanced session.
    pub weight: u32,
}

/// The order sets are offered in, and their weight in a balanced session.
///
/// ARCTIC sentences cover English sounds fastest; everyday sentences teach conversational rhythm;
/// short phrases are for tired days and are useful as recordings in their own right.
const BUILTIN: &[(&str, &str, u32)] = &[
    (
        "arctic-en",
        include_str!("../../../shared/prompts/arctic-en.json"),
        3,
    ),
    (
        "everyday-en",
        include_str!("../../../shared/prompts/everyday-en.json"),
        2,
    ),
    (
        "phrases-en",
        include_str!("../../../shared/prompts/phrases-en.json"),
        1,
    ),
];

/// The id used for the person's own phrases (names, places, sayings).
pub const PERSONAL_SET: &str = "personal";
const PERSONAL_WEIGHT: u32 = 1;

pub struct Library {
    sets: Vec<(PromptSet, u32)>,
    by_id: HashMap<String, (usize, usize)>,
}

/// The prompt sets shipped with this build.
pub fn library() -> &'static Library {
    static LIBRARY: OnceLock<Library> = OnceLock::new();
    LIBRARY.get_or_init(|| {
        let sets = BUILTIN
            .iter()
            .map(|(id, json, weight)| {
                let set: PromptSet = serde_json::from_str(json)
                    .unwrap_or_else(|e| panic!("shared/prompts/{id}.json is invalid: {e}"));
                assert_eq!(&set.id, id, "prompt set id must match its file name");
                (set, *weight)
            })
            .collect();
        Library::new(sets)
    })
}

impl Library {
    pub fn new(sets: Vec<(PromptSet, u32)>) -> Self {
        let mut by_id = HashMap::new();
        for (si, (set, _)) in sets.iter().enumerate() {
            for (pi, p) in set.prompts.iter().enumerate() {
                by_id.insert(p.id.clone(), (si, pi));
            }
        }
        Self { sets, by_id }
    }

    pub fn sets(&self) -> impl Iterator<Item = &PromptSet> {
        self.sets.iter().map(|(s, _)| s)
    }

    pub fn infos(&self) -> Vec<PromptSetInfo> {
        self.sets
            .iter()
            .map(|(s, w)| PromptSetInfo {
                id: s.id.clone(),
                language: s.language.clone(),
                title: s.title.clone(),
                description: s.description.clone(),
                license: s.license.clone(),
                source: s.source.clone(),
                attribution: s.attribution.clone(),
                count: s.prompts.len(),
                weight: *w,
            })
            .collect()
    }

    pub fn get(&self, prompt_id: &str) -> Option<(&PromptSet, &Prompt)> {
        self.by_id.get(prompt_id).map(|&(si, pi)| {
            let set = &self.sets[si].0;
            (set, &set.prompts[pi])
        })
    }

    pub fn total(&self) -> usize {
        self.sets.iter().map(|(s, _)| s.prompts.len()).sum()
    }

    /// All distinct phonemes and adjacent phoneme pairs across the built-in sets.
    pub fn inventory(&self) -> &Inventory {
        static INVENTORY: OnceLock<Inventory> = OnceLock::new();
        INVENTORY.get_or_init(|| {
            let mut inv = Inventory::default();
            for (set, _) in &self.sets {
                for p in &set.prompts {
                    if let Some(ph) = &p.ph {
                        inv.add(ph);
                    }
                }
            }
            inv
        })
    }
}

/// Distinct sounds (phonemes) and sound pairs (diphones).
#[derive(Debug, Default, Clone)]
pub struct Inventory {
    pub phonemes: HashSet<String>,
    pub diphones: HashSet<(String, String)>,
}

impl Inventory {
    /// Adds a prompt's phonemes. Pairs are counted within words and across word boundaries,
    /// as they are spoken.
    pub fn add(&mut self, ph: &str) {
        let mut prev: Option<&str> = None;
        for p in ph.split([' ', '_']).filter(|p| !p.is_empty()) {
            self.phonemes.insert(p.to_string());
            if let Some(a) = prev {
                self.diphones.insert((a.to_string(), p.to_string()));
            }
            prev = Some(p);
        }
    }
}

/// How the person's voice feels today. Tired days get shorter sessions and shorter sentences.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "kebab-case")]
pub enum Energy {
    Strong,
    #[default]
    Okay,
    Tired,
}

/// A prompt chosen for a session.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct QueuedPrompt {
    pub id: String,
    pub set_id: String,
    pub text: String,
}

/// A phrase the person added themselves: names of family and pets, places, sayings.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CustomPrompt {
    pub id: String,
    pub text: String,
    pub created_at: String,
}

/// Picks the next `count` prompts that still need recording.
///
/// Sets take turns in proportion to their weight (so a session mixes sound-rich sentences,
/// everyday talk and the person's own phrases). On tired days the shortest of the next few
/// prompts in each set is chosen first. `enabled` limits the sets; empty means all.
pub fn next_prompts(
    library: &Library,
    custom: &[CustomPrompt],
    done: &HashSet<String>,
    enabled: &[String],
    energy: Energy,
    count: usize,
) -> Vec<QueuedPrompt> {
    struct Source<'a> {
        set_id: String,
        weight: u32,
        items: Vec<(&'a str, &'a str)>,
        taken: usize,
    }
    let wanted = |id: &str| enabled.is_empty() || enabled.iter().any(|e| e == id);
    let mut sources: Vec<Source> = Vec::new();
    if wanted(PERSONAL_SET) {
        let items: Vec<_> = custom
            .iter()
            .filter(|c| !done.contains(&c.id))
            .map(|c| (c.id.as_str(), c.text.as_str()))
            .collect();
        if !items.is_empty() {
            sources.push(Source {
                set_id: PERSONAL_SET.into(),
                weight: PERSONAL_WEIGHT,
                items,
                taken: 0,
            });
        }
    }
    for (set, weight) in &library.sets {
        if !wanted(&set.id) {
            continue;
        }
        let items: Vec<_> = set
            .prompts
            .iter()
            .filter(|p| !done.contains(&p.id))
            .map(|p| (p.id.as_str(), p.text.as_str()))
            .collect();
        if !items.is_empty() {
            sources.push(Source {
                set_id: set.id.clone(),
                weight: *weight,
                items,
                taken: 0,
            });
        }
    }

    let window = match energy {
        Energy::Tired => 8,
        Energy::Okay | Energy::Strong => 1,
    };
    let mut out = Vec::with_capacity(count);
    while out.len() < count {
        // The source furthest behind its share goes next; ties go to the earlier set.
        let Some(si) = sources
            .iter()
            .enumerate()
            .filter(|(_, s)| !s.items.is_empty())
            .min_by(|(_, a), (_, b)| {
                let ra = a.taken as f64 / a.weight.max(1) as f64;
                let rb = b.taken as f64 / b.weight.max(1) as f64;
                ra.total_cmp(&rb)
            })
            .map(|(i, _)| i)
        else {
            break;
        };
        let source = &mut sources[si];
        let pick = source
            .items
            .iter()
            .take(window)
            .enumerate()
            .min_by_key(|(_, (_, text))| text.len())
            .map(|(i, _)| i)
            .unwrap_or(0);
        let (id, text) = source.items.remove(pick);
        source.taken += 1;
        out.push(QueuedPrompt {
            id: id.to_string(),
            set_id: source.set_id.clone(),
            text: text.to_string(),
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn set(id: &str, texts: &[&str]) -> PromptSet {
        PromptSet {
            id: id.into(),
            language: "en".into(),
            title: id.into(),
            description: String::new(),
            license: "CC0-1.0".into(),
            source: "test".into(),
            attribution: None,
            prompts: texts
                .iter()
                .enumerate()
                .map(|(i, t)| Prompt {
                    id: format!("{id}-{i}"),
                    text: t.to_string(),
                    ph: None,
                })
                .collect(),
        }
    }

    #[test]
    fn builtin_sets_load_and_ids_are_unique() {
        let lib = library();
        let mut ids = HashSet::new();
        for s in lib.sets() {
            assert!(!s.prompts.is_empty(), "{} is empty", s.id);
            for p in &s.prompts {
                assert!(ids.insert(p.id.clone()), "duplicate prompt id {}", p.id);
                assert!(!p.text.trim().is_empty());
            }
        }
        assert!(lib.total() > 1500, "{}", lib.total());
        assert!(lib.get("arctic_a0001").is_some());
    }

    #[test]
    fn builtin_sets_have_phonemes() {
        let lib = library();
        for s in lib.sets() {
            let missing = s.prompts.iter().filter(|p| p.ph.is_none()).count();
            assert_eq!(missing, 0, "{}: {missing} prompts without phonemes", s.id);
        }
        let inv = lib.inventory();
        assert!(inv.phonemes.len() > 35, "{}", inv.phonemes.len());
        assert!(inv.diphones.len() > 800, "{}", inv.diphones.len());
    }

    #[test]
    fn sets_take_turns_by_weight() {
        let lib = Library::new(vec![
            (set("a", &["a1", "a2", "a3", "a4", "a5", "a6"]), 2),
            (set("b", &["b1", "b2", "b3"]), 1),
        ]);
        let q = next_prompts(&lib, &[], &HashSet::new(), &[], Energy::Okay, 6);
        let sets: Vec<_> = q.iter().map(|p| p.set_id.as_str()).collect();
        assert_eq!(sets, ["a", "b", "a", "a", "b", "a"]);
    }

    #[test]
    fn recorded_prompts_are_skipped() {
        let lib = Library::new(vec![(set("a", &["one", "two", "three"]), 1)]);
        let done: HashSet<String> = ["a-0".to_string()].into();
        let q = next_prompts(&lib, &[], &done, &[], Energy::Okay, 5);
        assert_eq!(q.len(), 2);
        assert_eq!(q[0].id, "a-1");
    }

    #[test]
    fn tired_days_prefer_short_sentences() {
        let lib = Library::new(vec![(
            set(
                "a",
                &[
                    "A rather long sentence to read today.",
                    "Short one.",
                    "Medium sentence here.",
                ],
            ),
            1,
        )]);
        let q = next_prompts(&lib, &[], &HashSet::new(), &[], Energy::Tired, 1);
        assert_eq!(q[0].text, "Short one.");
        let q = next_prompts(&lib, &[], &HashSet::new(), &[], Energy::Okay, 1);
        assert_eq!(q[0].text, "A rather long sentence to read today.");
    }

    #[test]
    fn personal_phrases_are_mixed_in_and_can_be_filtered() {
        let lib = Library::new(vec![(set("a", &["a1", "a2", "a3"]), 3)]);
        let custom = vec![CustomPrompt {
            id: "personal-1".into(),
            text: "Biscuit, come here!".into(),
            created_at: String::new(),
        }];
        let q = next_prompts(&lib, &custom, &HashSet::new(), &[], Energy::Okay, 4);
        assert_eq!(q[0].set_id, PERSONAL_SET);
        let only_a = next_prompts(
            &lib,
            &custom,
            &HashSet::new(),
            &["a".into()],
            Energy::Okay,
            4,
        );
        assert!(only_a.iter().all(|p| p.set_id == "a"));
    }

    #[test]
    fn inventory_counts_pairs_across_words() {
        let mut inv = Inventory::default();
        inv.add("h_@_l oU");
        assert_eq!(inv.phonemes.len(), 4);
        assert!(inv.diphones.contains(&("l".into(), "oU".into())));
        assert_eq!(inv.diphones.len(), 3);
    }
}
