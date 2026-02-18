use serde::{Deserialize, Serialize};

pub const SUPPORTED_BROWSERS: [&str; 9] = [
    "firefox", "chrome", "chromium", "brave", "edge", "opera", "vivaldi", "whale", "safari",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SetupAnswers {
    pub archive_directory: String,
    pub cookie_source: String,
    pub cookie_browser: String,
    pub cookie_profile: String,
    pub write_subtitles: bool,
    pub write_thumbnail: bool,
    pub generate_nfo: bool,
}

impl Default for SetupAnswers {
    fn default() -> Self {
        Self {
            archive_directory: "~/Videos/media/youtube/".to_string(),
            cookie_source: "browser".to_string(),
            cookie_browser: "firefox".to_string(),
            cookie_profile: String::new(),
            write_subtitles: true,
            write_thumbnail: true,
            generate_nfo: true,
        }
    }
}

impl SetupAnswers {
    pub fn normalize(&mut self) {
        if self.archive_directory.trim().is_empty() {
            self.archive_directory = "~/Videos/media/youtube/".to_string();
        }
        if self.cookie_source != "browser" && self.cookie_source != "manual_file" {
            self.cookie_source = "manual_file".to_string();
        }
        if !SUPPORTED_BROWSERS.contains(&self.cookie_browser.as_str()) {
            self.cookie_browser = "firefox".to_string();
        }
        if self.cookie_source != "browser" {
            self.cookie_profile.clear();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::SetupAnswers;

    #[test]
    fn defaults_prefer_browser_cookie_source() {
        let answers = SetupAnswers::default();
        assert_eq!(answers.cookie_source, "browser");
        assert_eq!(answers.cookie_browser, "firefox");
    }
}
