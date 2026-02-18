use ratatui::{
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Text},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap},
    Frame,
};

use crate::{
    model::SUPPORTED_BROWSERS,
    state::{SectionState, Step, WizardState},
};

const ACCENT: Color = Color::Rgb(230, 47, 47);
const TEXT: Color = Color::Rgb(238, 232, 207);
const BG: Color = Color::Rgb(20, 20, 20);
const TEXT_DIM: Color = Color::Rgb(176, 170, 149);
const TEXT_LOCKED: Color = Color::Rgb(130, 126, 113);
const TEXT_DISABLED: Color = Color::Rgb(98, 96, 88);

const TARGET_RATIO_NUM: u16 = 8;
const TARGET_RATIO_DEN: u16 = 3;
const MAX_CARD_WIDTH: u16 = 96;
const MIN_CARD_WIDTH: u16 = 36;
const MIN_CARD_HEIGHT: u16 = 10;
const MIN_ONE_PAGE_INNER_WIDTH: u16 = 56;
const MIN_ONE_PAGE_INNER_HEIGHT: u16 = 20;
const MAX_CONTENT_WIDTH: u16 = 76;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RenderMode {
    OnePageProgressive,
    PagedFallback,
}

pub fn centered_card_4_3(area: Rect) -> Rect {
    let max_width = area.width.saturating_sub(4).max(MIN_CARD_WIDTH);
    let max_height = area.height.saturating_sub(2).max(MIN_CARD_HEIGHT);

    let mut width = max_width.min(MAX_CARD_WIDTH);
    let mut height = ((width as u32) * (TARGET_RATIO_DEN as u32) / (TARGET_RATIO_NUM as u32))
        .max(MIN_CARD_HEIGHT as u32) as u16;

    if height > max_height {
        height = max_height;
        width = ((height as u32) * (TARGET_RATIO_NUM as u32) / (TARGET_RATIO_DEN as u32))
            .min(max_width as u32) as u16;
    }

    if width < MIN_CARD_WIDTH.min(max_width) {
        width = MIN_CARD_WIDTH.min(max_width);
    }
    if height < MIN_CARD_HEIGHT.min(max_height) {
        height = MIN_CARD_HEIGHT.min(max_height);
    }

    let x = area.x + area.width.saturating_sub(width) / 2;
    let y = area.y + area.height.saturating_sub(height) / 2;
    Rect::new(x, y, width, height)
}

pub fn render(frame: &mut Frame, state: &WizardState) {
    let card = centered_card_4_3(frame.area());
    let block = Block::default()
        .title(" First-run Setup ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(ACCENT))
        .style(Style::default().fg(TEXT).bg(BG));
    let inner = block.inner(card);
    frame.render_widget(block, card);

    match select_render_mode(inner) {
        RenderMode::OnePageProgressive => render_one_page(frame, state, inner),
        RenderMode::PagedFallback => render_paged(frame, state, inner),
    }
}

fn select_render_mode(inner: Rect) -> RenderMode {
    if inner.width >= MIN_ONE_PAGE_INNER_WIDTH && inner.height >= MIN_ONE_PAGE_INNER_HEIGHT {
        RenderMode::OnePageProgressive
    } else {
        RenderMode::PagedFallback
    }
}

fn centered_column(area: Rect, max_width: u16) -> Rect {
    let width = area.width.min(max_width).max(1);
    let x = area.x + area.width.saturating_sub(width) / 2;
    Rect::new(x, area.y, width, area.height)
}

fn render_one_page(frame: &mut Frame, state: &WizardState, area: Rect) {
    let content = centered_column(area, MAX_CONTENT_WIDTH);
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(2),
            Constraint::Min(8),
            Constraint::Length(1),
        ])
        .split(content);

    let (progress_step, progress_total) = state.progress();
    let title = step_title(state.step());
    let header = Paragraph::new(format!("Step {progress_step}/{progress_total} · {title}"))
        .style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD));
    frame.render_widget(header, chunks[0]);

    let mut lines: Vec<Line> = Vec::new();
    append_archive_section(&mut lines, state);
    append_cookie_source_section(&mut lines, state);
    append_cookie_browser_section(&mut lines, state);
    append_cookie_profile_section(&mut lines, state);
    append_defaults_section(&mut lines, state);
    append_review_section(&mut lines, state);

    let body = Paragraph::new(Text::from(lines)).wrap(Wrap { trim: false });
    frame.render_widget(body, chunks[1]);

    let hint =
        Paragraph::new("j/k or arrows move, Enter confirm, Space toggle, b back, Esc cancel")
            .style(Style::default().fg(TEXT_DIM).add_modifier(Modifier::DIM));
    frame.render_widget(hint, chunks[2]);
}

fn append_archive_section(lines: &mut Vec<Line>, state: &WizardState) {
    let section = state.section_state(Step::ArchiveDirectory);
    push_section_header(lines, section, "Archive directory");
    push_section_line(
        lines,
        section,
        format!("  {}", state.archive_input()),
        section == SectionState::Active,
    );
}

fn append_cookie_source_section(lines: &mut Vec<Line>, state: &WizardState) {
    let section = state.section_state(Step::CookieSource);
    push_section_header(lines, section, "Cookie source");
    for (idx, option) in state.cookie_source_options().iter().enumerate() {
        let marker = if idx == state.cookie_source_index() {
            "●"
        } else {
            "○"
        };
        push_section_line(
            lines,
            section,
            format!("  {marker} {option}"),
            section == SectionState::Active && idx == state.cookie_source_index(),
        );
    }
}

fn append_cookie_browser_section(lines: &mut Vec<Line>, state: &WizardState) {
    let section = state.section_state(Step::CookieBrowser);
    push_section_header(lines, section, "Cookie browser");
    if !state.is_step_enabled(Step::CookieBrowser) {
        push_section_line(
            lines,
            SectionState::Disabled,
            "  inactive: set cookie source to browser".to_string(),
            false,
        );
        return;
    }

    for (row_idx, chunk) in SUPPORTED_BROWSERS.chunks(3).enumerate() {
        let mut row = String::from("  ");
        for (offset, browser) in chunk.iter().enumerate() {
            let index = row_idx * 3 + offset;
            let marker = if index == state.cookie_browser_index() {
                "●"
            } else {
                "○"
            };
            row.push_str(marker);
            row.push(' ');
            row.push_str(browser);
            if offset + 1 < chunk.len() {
                row.push_str("   ");
            }
        }
        push_section_line(
            lines,
            section,
            row,
            section == SectionState::Active
                && chunk
                    .iter()
                    .enumerate()
                    .any(|(offset, _)| row_idx * 3 + offset == state.cookie_browser_index()),
        );
    }
}

fn append_cookie_profile_section(lines: &mut Vec<Line>, state: &WizardState) {
    let section = state.section_state(Step::CookieProfile);
    push_section_header(lines, section, "Cookie profile (optional)");
    if !state.is_step_enabled(Step::CookieProfile) {
        push_section_line(
            lines,
            SectionState::Disabled,
            "  inactive: using manual_file mode".to_string(),
            false,
        );
        return;
    }
    let value = if state.profile_input().is_empty() {
        "(auto)"
    } else {
        state.profile_input()
    };
    push_section_line(
        lines,
        section,
        format!("  {value}"),
        section == SectionState::Active,
    );
}

fn append_defaults_section(lines: &mut Vec<Line>, state: &WizardState) {
    let section = state.section_state(Step::DownloadDefaults);
    push_section_header(lines, section, "Download defaults");
    for (idx, item) in state.default_items().iter().enumerate() {
        push_section_line(
            lines,
            section,
            format!("  {item}"),
            section == SectionState::Active && idx == state.defaults_index(),
        );
    }
}

fn append_review_section(lines: &mut Vec<Line>, state: &WizardState) {
    let section = state.section_state(Step::Review);
    push_section_header(lines, section, "Review and confirm");
    push_section_line(
        lines,
        section,
        format!("  archive: {}", state.answers.archive_directory),
        false,
    );
    push_section_line(
        lines,
        section,
        format!(
            "  cookies: source={} browser={} profile={}",
            state.answers.cookie_source,
            state.answers.cookie_browser,
            if state.answers.cookie_profile.is_empty() {
                "(auto)"
            } else {
                &state.answers.cookie_profile
            }
        ),
        false,
    );
    push_section_line(
        lines,
        section,
        format!(
            "  defaults: subtitles={} thumbnails={} nfo={}",
            state.answers.write_subtitles,
            state.answers.write_thumbnail,
            state.answers.generate_nfo
        ),
        false,
    );

    for (idx, option) in state.review_options().iter().enumerate() {
        let marker = if idx == state.review_index() {
            "●"
        } else {
            "○"
        };
        push_section_line(
            lines,
            section,
            format!("  {marker} {option}"),
            section == SectionState::Active && idx == state.review_index(),
        );
    }
}

fn push_section_header(lines: &mut Vec<Line>, section: SectionState, title: &str) {
    let marker = match section {
        SectionState::Active => "▶",
        SectionState::Unlocked => "•",
        SectionState::Locked => "·",
        SectionState::Disabled => "○",
    };
    lines.push(Line::styled(
        format!("{marker} {title}"),
        section_title_style(section),
    ));
}

fn push_section_line(
    lines: &mut Vec<Line>,
    section: SectionState,
    content: String,
    is_selected: bool,
) {
    let mut style = section_text_style(section);
    if is_selected {
        style = style.fg(ACCENT).add_modifier(Modifier::BOLD);
    }
    lines.push(Line::styled(content, style));
}

fn section_title_style(section: SectionState) -> Style {
    match section {
        SectionState::Active => Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
        SectionState::Unlocked => Style::default().fg(TEXT_DIM).add_modifier(Modifier::DIM),
        SectionState::Locked => Style::default().fg(TEXT_LOCKED).add_modifier(Modifier::DIM),
        SectionState::Disabled => Style::default()
            .fg(TEXT_DISABLED)
            .add_modifier(Modifier::DIM),
    }
}

fn section_text_style(section: SectionState) -> Style {
    match section {
        SectionState::Active => Style::default().fg(TEXT),
        SectionState::Unlocked => Style::default().fg(TEXT_DIM).add_modifier(Modifier::DIM),
        SectionState::Locked => Style::default().fg(TEXT_LOCKED).add_modifier(Modifier::DIM),
        SectionState::Disabled => Style::default()
            .fg(TEXT_DISABLED)
            .add_modifier(Modifier::DIM),
    }
}

fn render_paged(frame: &mut Frame, state: &WizardState, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Length(2),
            Constraint::Min(3),
            Constraint::Length(2),
        ])
        .split(area);

    let (progress_step, progress_total) = state.progress();
    let progress = Paragraph::new(format!("Step {progress_step}/{progress_total}"))
        .style(Style::default().fg(TEXT));
    frame.render_widget(progress, chunks[0]);

    let title = step_title(state.step());
    frame.render_widget(
        Paragraph::new(title).style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)),
        chunks[1],
    );

    render_paged_step_content(frame, state, chunks[2]);

    let hint = Paragraph::new("j/k or arrows move, Enter confirm, b back, Esc cancel")
        .style(Style::default().fg(TEXT_DIM).add_modifier(Modifier::DIM));
    frame.render_widget(hint, chunks[3]);
}

fn render_paged_step_content(frame: &mut Frame, state: &WizardState, area: Rect) {
    match state.step() {
        Step::ArchiveDirectory => {
            let input = Paragraph::new(state.archive_input())
                .block(
                    Block::default()
                        .borders(Borders::ALL)
                        .border_style(Style::default().fg(ACCENT)),
                )
                .wrap(Wrap { trim: false });
            frame.render_widget(input, area);
        }
        Step::CookieSource => {
            let options = state.cookie_source_options();
            let items = options
                .iter()
                .enumerate()
                .map(|(idx, option)| {
                    let prefix = if idx == state.cookie_source_index() {
                        "●"
                    } else {
                        "○"
                    };
                    ListItem::new(format!("{prefix} {option}"))
                })
                .collect::<Vec<_>>();
            let mut list_state =
                ListState::default().with_selected(Some(state.cookie_source_index()));
            let list = List::new(items).highlight_style(Style::default().fg(ACCENT));
            frame.render_stateful_widget(list, area, &mut list_state);
        }
        Step::CookieBrowser => {
            let items = SUPPORTED_BROWSERS
                .iter()
                .enumerate()
                .map(|(idx, browser)| {
                    let prefix = if idx == state.cookie_browser_index() {
                        "●"
                    } else {
                        "○"
                    };
                    ListItem::new(format!("{prefix} {browser}"))
                })
                .collect::<Vec<_>>();
            let mut list_state =
                ListState::default().with_selected(Some(state.cookie_browser_index()));
            let list = List::new(items).highlight_style(Style::default().fg(ACCENT));
            frame.render_stateful_widget(list, area, &mut list_state);
        }
        Step::CookieProfile => {
            let input = Paragraph::new(state.profile_input())
                .block(
                    Block::default()
                        .borders(Borders::ALL)
                        .border_style(Style::default().fg(ACCENT)),
                )
                .wrap(Wrap { trim: false });
            frame.render_widget(input, area);
        }
        Step::DownloadDefaults => {
            let default_items = state.default_items();
            let items = default_items
                .iter()
                .map(|item| ListItem::new(item.as_str()))
                .collect::<Vec<_>>();
            let mut list_state = ListState::default().with_selected(Some(state.defaults_index()));
            let list = List::new(items).highlight_style(Style::default().fg(ACCENT));
            frame.render_stateful_widget(list, area, &mut list_state);
        }
        Step::Review => {
            let lines = state.review_lines();
            let mut content = lines
                .iter()
                .map(|line| Line::raw(line.clone()))
                .collect::<Vec<_>>();
            content.push(Line::raw(""));
            for (idx, option) in state.review_options().iter().enumerate() {
                let marker = if idx == state.review_index() {
                    ">"
                } else {
                    " "
                };
                content.push(Line::raw(format!("{marker} {option}")));
            }
            frame.render_widget(
                Paragraph::new(Text::from(content)).wrap(Wrap { trim: false }),
                area,
            );
        }
    }
}

fn step_title(step: Step) -> &'static str {
    match step {
        Step::ArchiveDirectory => "Archive directory",
        Step::CookieSource => "Cookie source",
        Step::CookieBrowser => "Cookie browser",
        Step::CookieProfile => "Cookie profile (optional)",
        Step::DownloadDefaults => "Download defaults",
        Step::Review => "Review setup",
    }
}

#[cfg(test)]
mod tests {
    use ratatui::{backend::TestBackend, Terminal};

    use crate::{model::SetupAnswers, state::WizardState};

    use super::{centered_card_4_3, render, select_render_mode, RenderMode};

    #[test]
    fn centered_card_stays_within_bounds() {
        let area = ratatui::layout::Rect::new(0, 0, 120, 60);
        let card = centered_card_4_3(area);
        assert!(card.x >= area.x);
        assert!(card.y >= area.y);
        assert!(card.width <= area.width);
        assert!(card.height <= area.height);
        let ratio = card.width as f32 / card.height as f32;
        assert!(ratio > 2.3 && ratio < 2.95);
    }

    #[test]
    fn large_terminal_uses_one_page_mode() {
        let area = ratatui::layout::Rect::new(0, 0, 100, 34);
        assert_eq!(select_render_mode(area), RenderMode::OnePageProgressive);
    }

    #[test]
    fn small_terminal_uses_paged_fallback_mode() {
        let area = ratatui::layout::Rect::new(0, 0, 40, 16);
        assert_eq!(select_render_mode(area), RenderMode::PagedFallback);
    }

    #[test]
    fn render_one_page_does_not_overflow_normal_terminal() {
        let backend = TestBackend::new(120, 40);
        let mut terminal = Terminal::new(backend).expect("terminal");
        let state = WizardState::new(SetupAnswers::default());
        terminal
            .draw(|frame| render(frame, &state))
            .expect("draw succeeds");
    }

    #[test]
    fn render_does_not_overflow_small_terminal() {
        let backend = TestBackend::new(40, 20);
        let mut terminal = Terminal::new(backend).expect("terminal");
        let state = WizardState::new(SetupAnswers::default());
        terminal
            .draw(|frame| render(frame, &state))
            .expect("draw succeeds");
    }
}
