use std::{env, fs, path::PathBuf};

use anyhow::{Context, Result};

mod app;
mod events;
mod model;
mod state;
mod ui;

use app::{run_wizard, WizardResult};
use model::SetupAnswers;

struct CliArgs {
    defaults_path: PathBuf,
    result_path: PathBuf,
}

fn parse_args() -> Result<CliArgs> {
    let mut defaults_path: Option<PathBuf> = None;
    let mut result_path: Option<PathBuf> = None;
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--defaults" => {
                let value = args
                    .next()
                    .context("missing value for --defaults argument")?;
                defaults_path = Some(PathBuf::from(value));
            }
            "--result" => {
                let value = args.next().context("missing value for --result argument")?;
                result_path = Some(PathBuf::from(value));
            }
            other => {
                anyhow::bail!("unknown argument: {other}");
            }
        }
    }

    Ok(CliArgs {
        defaults_path: defaults_path.context("missing required --defaults <path>")?,
        result_path: result_path.context("missing required --result <path>")?,
    })
}

fn main() -> Result<()> {
    let args = parse_args()?;
    let input = fs::read_to_string(&args.defaults_path).with_context(|| {
        format!(
            "failed reading defaults file: {}",
            args.defaults_path.display()
        )
    })?;

    let mut defaults = if input.trim().is_empty() {
        SetupAnswers::default()
    } else {
        serde_json::from_str::<SetupAnswers>(&input).with_context(|| {
            format!(
                "invalid setup defaults JSON at {}",
                args.defaults_path.display()
            )
        })?
    };
    defaults.normalize();

    match run_wizard(defaults)? {
        WizardResult::Cancelled => std::process::exit(10),
        WizardResult::Submitted(mut answers) => {
            answers.normalize();
            let output = serde_json::to_string(&answers)?;
            fs::write(&args.result_path, output).with_context(|| {
                format!("failed writing result file: {}", args.result_path.display())
            })?;
        }
    }

    Ok(())
}
