use std::{io, time::Duration};

use anyhow::Result;
use crossterm::{
    event::DisableMouseCapture,
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{backend::CrosstermBackend, Terminal};

use crate::{
    events::{next_event, AppEvent},
    model::SetupAnswers,
    state::{Action, WizardState},
    ui,
};

pub enum WizardResult {
    Submitted(SetupAnswers),
    Cancelled,
}

pub fn run_wizard(defaults: SetupAnswers) -> Result<WizardResult> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let run_result = run_loop(&mut terminal, defaults);

    let _ = disable_raw_mode();
    let _ = execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    );
    let _ = terminal.show_cursor();

    run_result
}

fn run_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    defaults: SetupAnswers,
) -> Result<WizardResult> {
    let mut state = WizardState::new(defaults);

    loop {
        terminal.draw(|frame| ui::render(frame, &state))?;
        match next_event(Duration::from_millis(100))? {
            AppEvent::Tick => {}
            AppEvent::Key(key) => match state.handle_key(key) {
                Action::None => {}
                Action::Cancel => return Ok(WizardResult::Cancelled),
                Action::Submit(answers) => return Ok(WizardResult::Submitted(answers)),
            },
        }
    }
}
