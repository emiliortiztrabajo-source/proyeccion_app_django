from django.core.management.base import BaseCommand, CommandError

from dashboard.models import Scenario, Expense, IncomeEntry, ExpenseChangeLog


class Command(BaseCommand):
    help = "Remove imported expenses and incomes for a given scenario (e.g., Escenario 2) to free DB storage when not used."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scenario-name",
            dest="scenario_name",
            default="ESCENARIO 2",
            help="Substring to identify the scenario to clean (default: 'ESCENARIO 2').",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Display counts without deleting anything.",
        )

    def handle(self, *args, **options):
        name_filter = options["scenario_name"].strip()
        if not name_filter:
            raise CommandError("scenario-name cannot be empty.")

        scenarios = Scenario.objects.filter(name__icontains=name_filter)
        if not scenarios.exists():
            raise CommandError(f"No scenarios found matching '{name_filter}'.")

        for scenario in scenarios:
            expenses_qs = Expense.objects.filter(scenario=scenario)
            incomes_qs = IncomeEntry.objects.filter(scenario=scenario)
            changelog_qs = ExpenseChangeLog.objects.filter(scenario=scenario)

            self.stdout.write(f"Scenario: {scenario.name} (id={scenario.id})")
            self.stdout.write(f"  Expenses: {expenses_qs.count()}")
            self.stdout.write(f"  Income entries: {incomes_qs.count()}")
            self.stdout.write(f"  Expense change logs: {changelog_qs.count()}")

            if options["dry_run"]:
                self.stdout.write("  (dry run - no changes made)")
                continue

            # Delete in a safe order to avoid FK constraints.
            changelog_qs.delete()
            incomes_qs.delete()
            expenses_qs.delete()

            self.stdout.write(self.style.SUCCESS("  Deleted all imported expenses/incomes for this scenario."))
