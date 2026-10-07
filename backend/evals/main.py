#!/usr/bin/env python3
"""运行评测的命令行入口."""

import argparse
import asyncio
import os
import sys
from typing import (
    Any,
    Dict,
    Optional,
)

import colorama
from colorama import (
    Fore,
    Style,
)

# 修正 app 包的导入路径（把 backend/ 目录加进 sys.path）
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.core.logging import logger
from evals.evaluator import Evaluator

# 默认配置
DEFAULT_CONFIG = {
    "generate_report": True,
    "model": settings.EVALUATION_LLM,
    "api_base": settings.EVALUATION_BASE_URL,
}


def print_title(title: str) -> None:
    """带颜色打印居中的标题.

    Args:
        title: 要打印的标题文本
    """
    print("\n" + "=" * 60)
    print(f"{Fore.CYAN}{Style.BRIGHT}{title.center(60)}{Style.RESET_ALL}")
    print("=" * 60 + "\n")


def print_info(message: str) -> None:
    """带颜色打印提示信息.

    Args:
        message: 要打印的消息
    """
    print(f"{Fore.GREEN}• {message}{Style.RESET_ALL}")


def print_warning(message: str) -> None:
    """带颜色打印告警信息.

    Args:
        message: 要打印的消息
    """
    print(f"{Fore.YELLOW}⚠ {message}{Style.RESET_ALL}")


def print_error(message: str) -> None:
    """带颜色打印错误信息.

    Args:
        message: 要打印的消息
    """
    print(f"{Fore.RED}✗ {message}{Style.RESET_ALL}")


def print_success(message: str) -> None:
    """带颜色打印成功信息.

    Args:
        message: 要打印的消息
    """
    print(f"{Fore.GREEN}✓ {message}{Style.RESET_ALL}")


def get_user_input(prompt: str, default: Optional[str] = None) -> Optional[str]:
    """带颜色提示地读取用户输入.

    Args:
        prompt: 显示的提示语
        default: 用户直接回车时采用的默认值

    Returns:
        用户输入或默认值（未提供默认值时可能是 None）
    """
    default_text = f" [{default}]" if default else ""
    user_input = input(f"{Fore.BLUE}{prompt}{default_text}: {Style.RESET_ALL}")
    return user_input if user_input else default


def get_yes_no(prompt: str, default: bool = True) -> bool:
    """向用户询问是/否.

    Args:
        prompt: 显示的提示语
        default: 用户直接回车时采用的默认值

    Returns:
        选“是”返回 True，选“否”返回 False
    """
    default_value = "Y/n" if default else "y/N"
    response = get_user_input(f"{prompt} {default_value}")

    if not response:
        return default

    return response.lower() in ("y", "yes")


def display_summary(report: Dict[str, Any]) -> None:
    """打印本次评测结果的汇总.

    Args:
        report: 评测报告
    """
    print_title("Evaluation Summary")

    print(f"{Fore.CYAN}Model:{Style.RESET_ALL} {report['model']}")
    print(f"{Fore.CYAN}Duration:{Style.RESET_ALL} {report['duration_seconds']} seconds")
    print(f"{Fore.CYAN}Total Traces:{Style.RESET_ALL} {report['total_traces']}")

    success_rate = 0
    if report["total_traces"] > 0:
        success_rate = (report["successful_traces"] / report["total_traces"]) * 100

    if success_rate > 80:
        status_color = Fore.GREEN
    elif success_rate > 50:
        status_color = Fore.YELLOW
    else:
        status_color = Fore.RED

    print(
        f"{Fore.CYAN}Success Rate:{Style.RESET_ALL} {status_color}{success_rate:.1f}%{Style.RESET_ALL} ({report['successful_traces']}/{report['total_traces']})"
    )

    print("\n" + f"{Fore.CYAN}Metrics Summary:{Style.RESET_ALL}")
    for metric_name, data in report["metrics_summary"].items():
        total = data["success_count"] + data["failure_count"]
        success_percent = 0
        if total > 0:
            success_percent = (data["success_count"] / total) * 100

        if success_percent > 80:
            status_color = Fore.GREEN
        elif success_percent > 50:
            status_color = Fore.YELLOW
        else:
            status_color = Fore.RED

        print(
            f"  • {metric_name}: {status_color}{success_percent:.1f}%{Style.RESET_ALL} success, avg score: {data['avg_score']:.2f}"
        )

    if report["generate_report_path"]:
        print(f"\n{Fore.CYAN}Report generated at:{Style.RESET_ALL} {report['generate_report_path']}")


async def run_evaluation(generate_report: bool = True) -> None:
    """执行整轮评测流程.

    Args:
        generate_report: 是否生成 JSON 报告
    """
    print_title("Starting Evaluation")
    print_info(f"Using model: {settings.EVALUATION_LLM}")
    print_info(f"Report generation: {'Enabled' if generate_report else 'Disabled'}")

    try:
        evaluator = Evaluator()
        await evaluator.run(generate_report_file=generate_report)

        print_success("Evaluation completed successfully!")

        # 打印结果汇总
        display_summary(evaluator.report)

    except Exception as e:
        print_error(f"Evaluation failed: {str(e)}")
        logger.error("evaluation_failed", error=str(e))
        sys.exit(1)


def display_configuration(config: Dict[str, Any]) -> None:
    """打印当前生效的配置.

    Args:
        config: 配置 dict
    """
    print_title("Configuration")
    print_info(f"Model: {config['model']}")
    print_info(f"API Base: {config['api_base']}")
    print_info(f"Generate Report: {'Yes' if config['generate_report'] else 'No'}")


def interactive_mode() -> None:
    """以交互模式运行评测器."""
    colorama.init()

    # 用默认值拷出一份配置
    config = DEFAULT_CONFIG.copy()

    print_title("Evaluation Runner")
    print_info("Welcome to the Evaluation Runner!")
    print_info("Press Enter to accept default values or input your own.")

    # 展示当前配置
    display_configuration(config)

    print("\n" + f"{Fore.CYAN}Configuration Options (press Enter to accept defaults):{Style.RESET_ALL}")

    # 让用户改配置，或直接沿用默认值
    change_config = get_yes_no("Would you like to change the default configuration?", default=False)

    if change_config:
        config["generate_report"] = get_yes_no("Generate JSON report?", default=config["generate_report"])

    print("\n")
    confirm = get_yes_no("Ready to start evaluation with these settings?", default=True)

    if confirm:
        asyncio.run(run_evaluation(generate_report=config["generate_report"]))
    else:
        print_warning("Evaluation canceled.")


def quick_mode() -> None:
    """按全部默认设置直接运行评测."""
    colorama.init()
    print_title("Quick Evaluation")
    print_info("Running evaluation with default settings...")
    print_info("(Press Ctrl+C to cancel)")

    # 展示默认配置
    display_configuration(DEFAULT_CONFIG)

    try:
        asyncio.run(run_evaluation(generate_report=DEFAULT_CONFIG["generate_report"]))
    except KeyboardInterrupt:
        print_warning("\nEvaluation canceled by user.")
        sys.exit(0)


def main() -> None:
    """命令行的入口函数."""
    parser = argparse.ArgumentParser(description="Run evaluations on model outputs")
    parser.add_argument("--no-report", action="store_true", help="Don't generate a JSON report")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")
    parser.add_argument("--quick", action="store_true", help="Run with all default settings (no prompts)")

    args = parser.parse_args()

    if args.quick:
        quick_mode()
    elif args.interactive:
        interactive_mode()
    else:
        # 按命令行参数运行
        asyncio.run(run_evaluation(generate_report=not args.no_report))


if __name__ == "__main__":
    main()
