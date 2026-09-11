import pytest

from apps.findings.models import Issue
from apps.roadmaps.models import Roadmap, RoadmapItem
from apps.roadmaps.services import (
    add_issue_to_roadmap,
    add_manual_item,
    create_roadmap,
    reorder_item,
)
from apps.websites.models import Website
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="Test Workspace")


@pytest.fixture
def website(workspace):
    return Website.objects.create(
        workspace=workspace,
        name="Test Site",
        submitted_url="https://example.com/",
        canonical_url="https://example.com/",
        normalized_host="example.com",
    )


def make_issue(workspace, website, **overrides):
    defaults = dict(
        workspace=workspace,
        website=website,
        rule_key="missing_title",
        fingerprint=f"fp-{RoadmapItem.objects.count()}-{overrides.get('affected_scope', '')}",
        title="Missing title",
        category="seo",
        current_severity="high",
        affected_scope="https://example.com/",
        recommendation="Add a title tag.",
        estimated_effort="Small",
        priority_class=Issue.PriorityClass.QUICK_WIN,
    )
    defaults.update(overrides)
    return Issue.objects.create(**defaults)


class TestCreateRoadmap:
    def test_creates_roadmap_tied_to_website_and_workspace(self, website, workspace):
        roadmap = create_roadmap(website, "Q1 Renovation")
        assert roadmap.website == website
        assert roadmap.workspace == workspace
        assert roadmap.status == Roadmap.Status.DRAFT


class TestAddIssueToRoadmap:
    def test_prefills_fields_from_issue(self, website, workspace):
        roadmap = create_roadmap(website, "Plan")
        issue = make_issue(workspace, website, title="No H1", recommendation="Add an H1.")
        item = add_issue_to_roadmap(roadmap, issue, phase=RoadmapItem.Phase.CRITICAL_REPAIRS)

        assert item.title == "No H1"
        assert item.recommendation == "Add an H1."
        assert item.issue == issue

    def test_editing_item_does_not_mutate_source_issue(self, website, workspace):
        roadmap = create_roadmap(website, "Plan")
        issue = make_issue(workspace, website, title="Original title")
        item = add_issue_to_roadmap(roadmap, issue, phase=RoadmapItem.Phase.CRITICAL_REPAIRS)

        item.title = "Edited for client"
        item.save()

        issue.refresh_from_db()
        assert issue.title == "Original title"

    def test_defaults_phase_from_priority_class_when_not_specified(self, website, workspace):
        roadmap = create_roadmap(website, "Plan")
        issue = make_issue(
            workspace, website, priority_class=Issue.PriorityClass.IMMEDIATE_RISK
        )
        item = add_issue_to_roadmap(roadmap, issue)
        assert item.phase == RoadmapItem.Phase.CRITICAL_REPAIRS

    def test_positions_increment_within_a_phase(self, website, workspace):
        roadmap = create_roadmap(website, "Plan")
        issue1 = make_issue(workspace, website, affected_scope="https://example.com/a")
        issue2 = make_issue(workspace, website, affected_scope="https://example.com/b")

        item1 = add_issue_to_roadmap(roadmap, issue1, phase=RoadmapItem.Phase.CRITICAL_REPAIRS)
        item2 = add_issue_to_roadmap(roadmap, issue2, phase=RoadmapItem.Phase.CRITICAL_REPAIRS)

        assert item1.position == 0
        assert item2.position == 1


class TestAddManualItem:
    def test_creates_item_with_no_linked_issue(self, website):
        roadmap = create_roadmap(website, "Plan")
        item = add_manual_item(
            roadmap,
            phase=RoadmapItem.Phase.GROWTH_COMPETITIVE,
            title="Redesign homepage hero",
            recommendation="Work with design team on new hero section.",
        )
        assert item.issue is None
        assert item.title == "Redesign homepage hero"


class TestReorderItem:
    def test_move_within_same_phase(self, website, workspace):
        roadmap = create_roadmap(website, "Plan")
        phase = RoadmapItem.Phase.CRITICAL_REPAIRS
        a = add_manual_item(roadmap, phase, "A")
        b = add_manual_item(roadmap, phase, "B")
        c = add_manual_item(roadmap, phase, "C")
        # Starting order: A(0), B(1), C(2)

        reorder_item(a, phase, 2)  # Move A to the end -> B, C, A

        a.refresh_from_db()
        b.refresh_from_db()
        c.refresh_from_db()
        ordered = sorted([a, b, c], key=lambda i: i.position)
        assert [i.title for i in ordered] == ["B", "C", "A"]
        # Positions stay contiguous 0..n-1
        assert [i.position for i in ordered] == [0, 1, 2]

    def test_move_across_phases(self, website):
        roadmap = create_roadmap(website, "Plan")
        critical = RoadmapItem.Phase.CRITICAL_REPAIRS
        growth = RoadmapItem.Phase.GROWTH_COMPETITIVE
        a = add_manual_item(roadmap, critical, "A")
        b = add_manual_item(roadmap, critical, "B")
        add_manual_item(roadmap, growth, "X")

        reorder_item(a, growth, 0)

        a.refresh_from_db()
        b.refresh_from_db()
        assert a.phase == growth
        assert a.position == 0
        # B closes the gap left in critical_repairs
        assert b.phase == critical
        assert b.position == 0

    def test_new_position_clamped_to_valid_range(self, website):
        roadmap = create_roadmap(website, "Plan")
        phase = RoadmapItem.Phase.CRITICAL_REPAIRS
        a = add_manual_item(roadmap, phase, "A")
        b = add_manual_item(roadmap, phase, "B")

        reorder_item(a, phase, 999)  # way out of range

        a.refresh_from_db()
        b.refresh_from_db()
        # Should clamp to the last valid index, not error or create a gap.
        assert a.position == 1
        assert b.position == 0
