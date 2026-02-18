use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

use crate::model::{SetupAnswers, SUPPORTED_BROWSERS};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Step {
    ArchiveDirectory,
    CookieSource,
    CookieBrowser,
    CookieProfile,
    DownloadDefaults,
    Review,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SectionState {
    Active,
    Unlocked,
    Locked,
    Disabled,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    None,
    Submit(SetupAnswers),
    Cancel,
}

pub struct WizardState {
    pub answers: SetupAnswers,
    step: Step,
    archive_input: String,
    profile_input: String,
    cookie_source_index: usize,
    cookie_browser_index: usize,
    defaults_index: usize,
    review_index: usize,
}

impl WizardState {
    const STEP_ORDER: [Step; 6] = [
        Step::ArchiveDirectory,
        Step::CookieSource,
        Step::CookieBrowser,
        Step::CookieProfile,
        Step::DownloadDefaults,
        Step::Review,
    ];

    pub fn new(mut defaults: SetupAnswers) -> Self {
        defaults.normalize();
        let cookie_source_index = if defaults.cookie_source == "browser" {
            0
        } else {
            1
        };
        let cookie_browser_index = SUPPORTED_BROWSERS
            .iter()
            .position(|browser| *browser == defaults.cookie_browser.as_str())
            .unwrap_or(0);
        Self {
            archive_input: defaults.archive_directory.clone(),
            profile_input: defaults.cookie_profile.clone(),
            answers: defaults,
            step: Step::ArchiveDirectory,
            cookie_source_index,
            cookie_browser_index,
            defaults_index: 0,
            review_index: 0,
        }
    }

    pub fn step(&self) -> Step {
        self.step
    }

    pub fn archive_input(&self) -> &str {
        &self.archive_input
    }

    pub fn profile_input(&self) -> &str {
        &self.profile_input
    }

    pub fn cookie_source_options(&self) -> [&str; 2] {
        ["browser", "manual_file"]
    }

    pub fn cookie_source_index(&self) -> usize {
        self.cookie_source_index
    }

    pub fn cookie_browser_index(&self) -> usize {
        self.cookie_browser_index
    }

    pub fn defaults_index(&self) -> usize {
        self.defaults_index
    }

    pub fn review_index(&self) -> usize {
        self.review_index
    }

    pub fn review_options(&self) -> [&str; 2] {
        ["Create setup files", "Back"]
    }

    pub fn section_state(&self, step: Step) -> SectionState {
        if !self.is_step_enabled(step) {
            return SectionState::Disabled;
        }
        let current_index = self.current_step_index();
        let step_index = Self::step_index(step);
        if step_index == current_index {
            SectionState::Active
        } else if step_index < current_index {
            SectionState::Unlocked
        } else {
            SectionState::Locked
        }
    }

    pub fn current_step_index(&self) -> usize {
        Self::step_index(self.step)
    }

    pub fn is_step_enabled(&self, step: Step) -> bool {
        !matches!(step, Step::CookieBrowser | Step::CookieProfile)
            || self.answers.cookie_source == "browser"
    }

    pub fn visible_steps(&self) -> Vec<Step> {
        let mut steps = vec![Step::ArchiveDirectory, Step::CookieSource];
        if self.answers.cookie_source == "browser" {
            steps.push(Step::CookieBrowser);
            steps.push(Step::CookieProfile);
        }
        steps.push(Step::DownloadDefaults);
        steps.push(Step::Review);
        steps
    }

    pub fn progress(&self) -> (usize, usize) {
        let steps = self.visible_steps();
        let index = steps
            .iter()
            .position(|step| *step == self.step)
            .unwrap_or(0);
        (index + 1, steps.len())
    }

    pub fn default_items(&self) -> [String; 3] {
        [
            format!(
                "{} Download subtitles",
                if self.answers.write_subtitles {
                    "◈"
                } else {
                    "◇"
                }
            ),
            format!(
                "{} Download thumbnails",
                if self.answers.write_thumbnail {
                    "◈"
                } else {
                    "◇"
                }
            ),
            format!(
                "{} Generate NFO metadata",
                if self.answers.generate_nfo {
                    "◈"
                } else {
                    "◇"
                }
            ),
        ]
    }

    pub fn review_lines(&self) -> [String; 7] {
        [
            format!("Archive directory: {}", self.answers.archive_directory),
            format!("Cookie source: {}", self.answers.cookie_source),
            format!("Cookie browser: {}", self.answers.cookie_browser),
            format!("Cookie profile: {}", self.answers.cookie_profile),
            format!("Download subtitles: {}", self.answers.write_subtitles),
            format!("Download thumbnails: {}", self.answers.write_thumbnail),
            format!("Generate NFO: {}", self.answers.generate_nfo),
        ]
    }

    pub fn handle_key(&mut self, key: KeyEvent) -> Action {
        if key.modifiers.contains(KeyModifiers::CONTROL)
            && matches!(key.code, KeyCode::Char('c') | KeyCode::Char('C'))
        {
            return Action::Cancel;
        }
        match key.code {
            KeyCode::Esc | KeyCode::Char('q') | KeyCode::Char('Q') => return Action::Cancel,
            KeyCode::Char('b') | KeyCode::Char('B') => {
                self.previous_step();
                return Action::None;
            }
            _ => {}
        }

        match self.step {
            Step::ArchiveDirectory => {
                self.handle_text_input(key, true);
                Action::None
            }
            Step::CookieSource => {
                Self::handle_choice_navigation(key, 2, &mut self.cookie_source_index);
                if matches!(key.code, KeyCode::Enter) {
                    self.answers.cookie_source = if self.cookie_source_index == 0 {
                        "browser".to_string()
                    } else {
                        self.answers.cookie_profile.clear();
                        "manual_file".to_string()
                    };
                    self.next_step();
                }
                Action::None
            }
            Step::CookieBrowser => {
                Self::handle_choice_navigation(
                    key,
                    SUPPORTED_BROWSERS.len(),
                    &mut self.cookie_browser_index,
                );
                if matches!(key.code, KeyCode::Enter) {
                    self.answers.cookie_browser =
                        SUPPORTED_BROWSERS[self.cookie_browser_index].to_string();
                    self.next_step();
                }
                Action::None
            }
            Step::CookieProfile => {
                self.handle_text_input(key, false);
                Action::None
            }
            Step::DownloadDefaults => {
                match key.code {
                    KeyCode::Char('j') | KeyCode::Down => {
                        self.defaults_index = (self.defaults_index + 1).min(2);
                    }
                    KeyCode::Char('k') | KeyCode::Up => {
                        self.defaults_index = self.defaults_index.saturating_sub(1);
                    }
                    KeyCode::Char(' ') => self.toggle_default(),
                    KeyCode::Enter => self.next_step(),
                    _ => {}
                }
                Action::None
            }
            Step::Review => {
                match key.code {
                    KeyCode::Char('j') | KeyCode::Down => {
                        self.review_index = (self.review_index + 1).min(1);
                    }
                    KeyCode::Char('k') | KeyCode::Up => {
                        self.review_index = self.review_index.saturating_sub(1);
                    }
                    KeyCode::Enter => {
                        if self.review_index == 0 {
                            return Action::Submit(self.answers.clone());
                        }
                        self.previous_step();
                    }
                    _ => {}
                }
                Action::None
            }
        }
    }

    fn handle_text_input(&mut self, key: KeyEvent, is_archive: bool) {
        let target = if is_archive {
            &mut self.archive_input
        } else {
            &mut self.profile_input
        };
        match key.code {
            KeyCode::Backspace => {
                target.pop();
            }
            KeyCode::Delete => {
                target.clear();
            }
            KeyCode::Char(character) => {
                target.push(character);
            }
            KeyCode::Enter => {
                if is_archive {
                    let value = target.trim();
                    if value.is_empty() {
                        target.push_str("~/Videos/media/youtube/");
                    }
                    self.answers.archive_directory = target.trim().to_string();
                } else {
                    self.answers.cookie_profile = target.trim().to_string();
                }
                self.next_step();
            }
            _ => {}
        }
    }

    fn handle_choice_navigation(key: KeyEvent, len: usize, selected: &mut usize) {
        if len == 0 {
            return;
        }
        match key.code {
            KeyCode::Char('j') | KeyCode::Down | KeyCode::Right => {
                *selected = (*selected + 1).min(len - 1);
            }
            KeyCode::Char('k') | KeyCode::Up | KeyCode::Left => {
                *selected = selected.saturating_sub(1);
            }
            _ => {}
        }
    }

    fn toggle_default(&mut self) {
        match self.defaults_index {
            0 => self.answers.write_subtitles = !self.answers.write_subtitles,
            1 => self.answers.write_thumbnail = !self.answers.write_thumbnail,
            2 => self.answers.generate_nfo = !self.answers.generate_nfo,
            _ => {}
        }
    }

    fn next_step(&mut self) {
        let steps = self.visible_steps();
        let Some(index) = steps.iter().position(|step| *step == self.step) else {
            return;
        };
        if index + 1 < steps.len() {
            self.step = steps[index + 1];
        }
    }

    fn previous_step(&mut self) {
        let steps = self.visible_steps();
        let Some(index) = steps.iter().position(|step| *step == self.step) else {
            return;
        };
        if index > 0 {
            self.step = steps[index - 1];
        }
    }

    fn step_index(step: Step) -> usize {
        Self::STEP_ORDER
            .iter()
            .position(|entry| *entry == step)
            .unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};

    use crate::model::SetupAnswers;

    use super::{Action, SectionState, Step, WizardState};

    fn key(code: KeyCode) -> KeyEvent {
        KeyEvent::new(code, KeyModifiers::empty())
    }

    #[test]
    fn visibility_skips_browser_steps_for_manual_source() {
        let mut state = WizardState::new(SetupAnswers::default());
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Down));
        state.handle_key(key(KeyCode::Enter));
        assert_eq!(state.step(), Step::DownloadDefaults);
    }

    #[test]
    fn browser_flow_includes_browser_and_profile_steps() {
        let mut state = WizardState::new(SetupAnswers::default());
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Enter));
        assert_eq!(state.step(), Step::CookieBrowser);
        state.handle_key(key(KeyCode::Enter));
        assert_eq!(state.step(), Step::CookieProfile);
    }

    #[test]
    fn defaults_toggle_uses_diamond_semantics() {
        let mut state = WizardState::new(SetupAnswers {
            cookie_source: "manual_file".to_string(),
            ..SetupAnswers::default()
        });
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Char(' ')));
        assert!(!state.answers.write_subtitles);
        assert!(state.default_items()[0].starts_with("◇"));
    }

    #[test]
    fn review_confirm_submits_answers() {
        let mut state = WizardState::new(SetupAnswers {
            cookie_source: "manual_file".to_string(),
            ..SetupAnswers::default()
        });
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Enter));
        let action = state.handle_key(key(KeyCode::Enter));
        match action {
            Action::Submit(answers) => {
                assert_eq!(answers.cookie_source, "manual_file");
            }
            other => panic!("expected submit action, got {other:?}"),
        }
    }

    #[test]
    fn section_state_marks_future_steps_locked_until_reached() {
        let mut state = WizardState::new(SetupAnswers {
            cookie_source: "manual_file".to_string(),
            ..SetupAnswers::default()
        });
        assert_eq!(
            state.section_state(Step::DownloadDefaults),
            SectionState::Locked
        );
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Enter));
        assert_eq!(
            state.section_state(Step::DownloadDefaults),
            SectionState::Active
        );
    }

    #[test]
    fn section_state_marks_browser_sections_disabled_for_manual_source() {
        let mut state = WizardState::new(SetupAnswers {
            cookie_source: "manual_file".to_string(),
            ..SetupAnswers::default()
        });
        state.handle_key(key(KeyCode::Enter));
        state.handle_key(key(KeyCode::Enter));
        assert_eq!(
            state.section_state(Step::CookieBrowser),
            SectionState::Disabled
        );
        assert_eq!(
            state.section_state(Step::CookieProfile),
            SectionState::Disabled
        );
    }

    #[test]
    fn backspace_edits_archive_text_without_navigation() {
        let mut state = WizardState::new(SetupAnswers::default());
        let initial = state.archive_input().len();
        state.handle_key(key(KeyCode::Backspace));
        assert_eq!(state.step(), Step::ArchiveDirectory);
        assert_eq!(state.archive_input().len(), initial.saturating_sub(1));
    }
}
