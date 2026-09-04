# OpenTrader Training Framework — Teacher/Student + Evaluation + Fine-tuning
from .programmatic_teacher import ProgrammaticTeacher, Scenario
from .teacher_student import TeacherStudentFramework, PatternBank
from .traderbench import TraderBench, Simulator, ScoreConfig
from .controller import TrainingController
from .data_builder import build_training_data, reflection_stats
from .finetune_cycle import run_finetune, read_status
from .reward_builder import (
    realized_pnl_reward,
    sharpe_windowed_reward,
    win_rate_reward,
    drawdown_penalty,
    portfolio_to_sharpe,
    composite_reward,
    reward_from_state,
    reward_consistency,
    detect_behavioral_loop,
    novelty_bonus,
    anti_loop_penalty,
    coach_guided_reward,
    behavioral_composite_reward,
)
from .rl_trainer import (
    run_grpo,
    run_grpo_from_objective,
    GRPOConfig,
    NotImplementedOnLocalGPU,
    BehavioralRLTrainer,
    RLTrainingConfig,
)
from .capability_distiller import (
    distill_all,
    distill_manifest,
    fold_capability,
    get_folded_capabilities,
    get_cumulative_scenarios,
)
from .research_model import (
    check_gate,
    build_triage_dataset,
    train_research_model,
    triage_finding,
    get_research_model_status,
)
from .research_runner import (
    generate_manifest,
    run_sweep,
    search_arxiv,
    search_hf_hub,
    should_research,
)
