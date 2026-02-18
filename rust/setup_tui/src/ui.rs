use ratatui::{
    layout::{Alignment, Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
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
const MAX_CONTENT_WIDTH: u16 = 78;
const BROWSER_CELL_GAP: usize = 3;

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
    if inner.width >= MIN_ONE_PAGE_INNER_WIDTH
        && inner.height >= one_page_required_height(inner.width)
    {
        RenderMode::OnePageProgressive
    } else {
        RenderMode::PagedFallback
    }
}

fn one_page_required_height(width: u16) -> u16 {
    let browser_rows =
        (SUPPORTED_BROWSERS.len() as u16).div_ceil(browser_grid_columns(width).max(1) as u16);
    25 + browser_rows
}

fn centered_column(area: Rect, max_width: u16) -> Rect {
    let width = area.width.min(max_width).max(1);
    let x = area.x + area.width.saturating_sub(width) / 2;
    Rect::new(x, area.y, width, area.height)
}

fn marker(selected: bool) -> &'static str {
    let ascii = std::env::var("YTDL_ARCHIVER_ASCII_MARKERS")
        .ok()
        .is_some_and(|value| value == "1" || value.eq_ignore_ascii_case("true"));
    match (ascii, selected) {
        (true, true) => "*",
        (true, false) => "o",
        (false, true) => "◈",
        (false, false) => "◇",
    }
}

fn render_one_page(frame: &mut Frame, state: &WizardState, area: Rect) {
    let content = centered_column(area, MAX_CONTENT_WIDTH);
    let padded = Rect::new(
        content.x,
        content.y.saturating_add(1),
        content.width,
        content.height.saturating_sub(2),
    );

    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Min(8),
            Constraint::Length(2),
        ])
        .split(padded);

    frame.render_widget(
        Paragraph::new("ytdl-archiver")
            .alignment(Alignment::Center)
            .style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)),
        chunks[0],
    );

    let (progress_step, progress_total) = state.progress();
    frame.render_widget(
        Paragraph::new(format!("Step {progress_step}/{progress_total}"))
            .alignment(Alignment::Center)
            .style(Style::default().fg(TEXT_DIM).add_modifier(Modifier::DIM)),
        chunks[1],
    );

    frame.render_widget(Paragraph::new(""), chunks[2]);

    let lines = build_one_page_lines(state, chunks[3].width);
    let body = Paragraph::new(Text::from(lines)).wrap(Wrap { trim: false });
    frame.render_widget(body, chunks[3]);

    let hint =
        Paragraph::new("arrows or j/k move · Enter next · Space toggle\nb back · Esc cancel")
            .alignment(Alignment::Center)
            .wrap(Wrap { trim: true })
            .style(Style::default().fg(TEXT_DIM).add_modifier(Modifier::DIM));
    frame.render_widget(hint, chunks[4]);
}

fn build_one_page_lines(state: &WizardState, width: u16) -> Vec<Line<'static>> {
    let mut lines: Vec<Line> = Vec::new();

    append_archive_section(&mut lines, state, width);
    push_divider(&mut lines, width);

    append_cookie_source_section(&mut lines, state, width);
    push_divider(&mut lines, width);

    append_cookie_browser_section(&mut lines, state, width);
    push_divider(&mut lines, width);

    append_cookie_profile_section(&mut lines, state, width);
    push_divider(&mut lines, width);

    append_defaults_section(&mut lines, state, width);
    push_divider(&mut lines, width);

    append_review_section(&mut lines, state);

    lines
}

fn append_archive_section(lines: &mut Vec<Line<'static>>, state: &WizardState, _width: u16) {
    let section = state.section_state(Step::ArchiveDirectory);
    push_section_header(
        lines,
        section,
        "Archive Directory (Enter where you want to archive media)",
    );
    push_section_line(
        lines,
        section,
        format!("  {}", state.archive_input()),
        section == SectionState::Active,
    );
}

fn append_cookie_source_section(lines: &mut Vec<Line<'static>>, state: &WizardState, width: u16) {
    let section = state.section_state(Step::CookieSource);
    push_section_header(
        lines,
        section,
        "Cookie Source (Recommended: browser [firefox])",
    );

    let options = state.cookie_source_options();
    let left = format!(
        "{} {}",
        marker(state.cookie_source_index() == 0),
        options[0]
    );
    let right = format!(
        "{} {}",
        marker(state.cookie_source_index() == 1),
        options[1]
    );
    let gap = source_gap(width, left.len(), right.len());
    let mut spans: Vec<Span> = Vec::new();

    spans.push(Span::styled(
        format!("  {left}"),
        option_style(
            section,
            section == SectionState::Active && state.cookie_source_index() == 0,
        ),
    ));
    spans.push(Span::raw(" ".repeat(gap)));
    spans.push(Span::styled(
        right,
        option_style(
            section,
            section == SectionState::Active && state.cookie_source_index() == 1,
        ),
    ));
    lines.push(Line::from(spans));
}

fn append_cookie_browser_section(lines: &mut Vec<Line<'static>>, state: &WizardState, width: u16) {
    let section = state.section_state(Step::CookieBrowser);
    push_section_header(
        lines,
        section,
        "Cookie Browser (For best functionality as of February 18, 2026: firefox)",
    );

    if !state.is_step_enabled(Step::CookieBrowser) {
        push_section_line(
            lines,
            SectionState::Disabled,
            "  inactive: set cookie source to browser".to_string(),
            false,
        );
        return;
    }

    let columns = browser_grid_columns(width);
    let cell_width = browser_cell_width();

    for row in SUPPORTED_BROWSERS.chunks(columns) {
        let mut spans: Vec<Span> = vec![Span::raw("  ")];
        for (idx_in_row, browser) in row.iter().enumerate() {
            let absolute_index = SUPPORTED_BROWSERS
                .iter()
                .position(|candidate| candidate == browser)
                .unwrap_or(0);
            let is_selected = absolute_index == state.cookie_browser_index();
            let token = format!("{} {}", marker(is_selected), browser,);
            let padded = format!("{token:<cell_width$}");
            spans.push(Span::styled(
                padded,
                option_style(section, section == SectionState::Active && is_selected),
            ));
            if idx_in_row + 1 < row.len() {
                spans.push(Span::raw(" ".repeat(BROWSER_CELL_GAP)));
            }
        }
        lines.push(Line::from(spans));
    }
}

fn append_cookie_profile_section(lines: &mut Vec<Line<'static>>, state: &WizardState, _width: u16) {
    let section = state.section_state(Step::CookieProfile);
    push_section_header(
        lines,
        section,
        "Cookie Profile (Optional profile name/path; blank = auto)",
    );
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

fn append_defaults_section(lines: &mut Vec<Line<'static>>, state: &WizardState, width: u16) {
    let section = state.section_state(Step::DownloadDefaults);
    push_section_header(lines, section, "Download Defaults (All true by default)");

    let options = [
        (state.answers.write_subtitles, "download subtitles"),
        (state.answers.write_thumbnail, "download thumbnails"),
        (state.answers.generate_nfo, "generate .nfo data"),
    ];

    let tokens = options
        .iter()
        .map(|(enabled, label)| format!("{} {}", marker(*enabled), label))
        .collect::<Vec<_>>();

    let horizontal = tokens.join("   ");
    let usable_width = width.saturating_sub(2) as usize;
    if horizontal.len() <= usable_width {
        let mut spans: Vec<Span> = vec![Span::raw("  ")];
        for (idx, token) in tokens.iter().enumerate() {
            spans.push(Span::styled(
                token.clone(),
                option_style(
                    section,
                    section == SectionState::Active && idx == state.defaults_index(),
                ),
            ));
            if idx + 1 < tokens.len() {
                spans.push(Span::raw("   "));
            }
        }
        lines.push(Line::from(spans));
    } else {
        for (idx, token) in tokens.iter().enumerate() {
            push_section_line(
                lines,
                section,
                format!("  {token}"),
                section == SectionState::Active && idx == state.defaults_index(),
            );
        }
    }
}

fn append_review_section(lines: &mut Vec<Line<'static>>, state: &WizardState) {
    let section = state.section_state(Step::Review);
    push_section_header(lines, section, "Review and Confirm");

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
        let is_selected = idx == state.review_index();
        push_section_line(
            lines,
            section,
            format!("  {} {option}", marker(is_selected)),
            section == SectionState::Active && is_selected,
        );
    }
}

fn source_gap(width: u16, left_len: usize, right_len: usize) -> usize {
    let usable = width.saturating_sub(2) as usize;
    let total = left_len + right_len;
    if usable <= total {
        3
    } else {
        (usable - total).min(12).max(3)
    }
}

fn browser_cell_width() -> usize {
    let longest = SUPPORTED_BROWSERS
        .iter()
        .map(|browser| browser.len())
        .max()
        .unwrap_or(7);
    2 + longest
}

fn browser_grid_columns(width: u16) -> usize {
    let usable = width.saturating_sub(2) as usize;
    let cell = browser_cell_width();
    for candidate in [5usize, 4, 3, 2] {
        let needed = candidate * cell + (candidate.saturating_sub(1) * BROWSER_CELL_GAP);
        if needed <= usable {
            return candidate;
        }
    }
    1
}

fn push_divider(lines: &mut Vec<Line<'static>>, width: u16) {
    let divider_len = width.saturating_sub(4) as usize;
    let divider = "─".repeat(divider_len.max(8));
    lines.push(Line::styled(
        format!("  {divider}"),
        Style::default().fg(TEXT_LOCKED).add_modifier(Modifier::DIM),
    ));
}

fn push_section_header(lines: &mut Vec<Line<'static>>, section: SectionState, title: &str) {
    lines.push(Line::styled(
        title.to_string(),
        section_title_style(section),
    ));
}

fn push_section_line(
    lines: &mut Vec<Line<'static>>,
    section: SectionState,
    content: String,
    is_selected: bool,
) {
    lines.push(Line::styled(content, option_style(section, is_selected)));
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

fn option_style(section: SectionState, is_selected: bool) -> Style {
    if is_selected {
        Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
    } else {
        section_text_style(section)
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

    let hint = Paragraph::new("arrows or j/k move · Enter next · b back · Esc cancel")
        .alignment(Alignment::Center)
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
                    let prefix = marker(idx == state.cookie_source_index());
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
                    let prefix = marker(idx == state.cookie_browser_index());
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
            let items = state
                .default_items()
                .iter()
                .map(|item| ListItem::new(item.clone()))
                .collect::<Vec<_>>();
            let mut list_state = ListState::default().with_selected(Some(state.defaults_index()));
            let list = List::new(items).highlight_style(Style::default().fg(ACCENT));
            frame.render_stateful_widget(list, area, &mut list_state);
        }
        Step::Review => {
            let mut content = state
                .review_lines()
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
        Step::ArchiveDirectory => "Archive Directory (Enter where you want to archive media)",
        Step::CookieSource => "Cookie Source (Recommended: browser [firefox])",
        Step::CookieBrowser => {
            "Cookie Browser (For best functionality as of February 18, 2026: firefox)"
        }
        Step::CookieProfile => "Cookie Profile (Optional profile name/path; blank = auto)",
        Step::DownloadDefaults => "Download Defaults (All true by default)",
        Step::Review => "Review and Confirm",
    }
}

#[cfg(test)]
mod tests {
    use ratatui::{backend::TestBackend, Terminal};

    use crate::{model::SetupAnswers, state::WizardState};

    use super::{
        browser_grid_columns as columns, centered_card_4_3, render, select_render_mode, RenderMode,
    };

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
    fn browser_grid_columns_degrade_by_width() {
        assert_eq!(columns(78), 5);
        assert_eq!(columns(58), 4);
        assert_eq!(columns(46), 3);
        assert_eq!(columns(34), 2);
    }

    #[test]
    fn render_one_page_contains_app_header() {
        let backend = TestBackend::new(120, 40);
        let mut terminal = Terminal::new(backend).expect("terminal");
        let state = WizardState::new(SetupAnswers::default());
        terminal
            .draw(|frame| render(frame, &state))
            .expect("draw succeeds");

        let snapshot = format!("{:?}", terminal.backend().buffer());
        assert!(snapshot.contains("ytdl-archiver"));
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
