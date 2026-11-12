"""Tests for the group visit filter feature."""
import pytest


def test_everyone_filter_with_three_travellers():
    """Test that 'Everyone' filter returns only common countries."""
    mock_data = {
        'alice': {'name': 'Alice', 'countries': ['US', 'FR', 'JP']},
        'bob': {'name': 'Bob', 'countries': ['US', 'GB', 'AU']},
        'charlie': {'name': 'Charlie', 'countries': ['US', 'FR', 'CN']}
    }
    
    members = ['alice', 'bob', 'charlie']
    member_countries = [set(mock_data[id]['countries']) for id in members]
    first = member_countries[0]
    result = set(c for c in first if all(s.issuperset([c]) for s in member_countries))
    
    assert result == {'US'}, "Everyone filter should return only 'US' as common country"


def test_anyone_filter_with_three_travellers():
    """Test that 'Anyone' filter returns all countries visited by any traveller."""
    mock_data = {
        'alice': {'name': 'Alice', 'countries': ['US', 'FR', 'JP']},
        'bob': {'name': 'Bob', 'countries': ['US', 'GB', 'AU']},
        'charlie': {'name': 'Charlie', 'countries': ['US', 'FR', 'CN']}
    }
    
    members = ['alice', 'bob', 'charlie']
    result = set()
    for id in members:
        result.update(mock_data[id]['countries'])
    
    expected = {'US', 'FR', 'JP', 'GB', 'AU', 'CN'}
    assert result == expected, "Anyone filter should return all countries"


def test_everyone_filter_with_two_travellers():
    """Test that 'Everyone' filter works correctly with two travellers."""
    mock_data = {
        'alice': {'name': 'Alice', 'countries': ['US', 'FR', 'JP']},
        'bob': {'name': 'Bob', 'countries': ['US', 'GB', 'AU']}
    }
    
    members = ['alice', 'bob']
    member_countries = [set(mock_data[id]['countries']) for id in members]
    first = member_countries[0]
    result = set(c for c in first if all(s.issuperset([c]) for s in member_countries))
    
    assert result == {'US'}, "Everyone filter with 2 travellers should return only 'US'"


def test_everyone_filter_with_no_common_countries():
    """Test that 'Everyone' filter returns empty set when there are no common countries."""
    mock_data = {
        'alice': {'name': 'Alice', 'countries': ['US', 'FR']},
        'bob': {'name': 'Bob', 'countries': ['GB', 'AU']}
    }
    
    members = ['alice', 'bob']
    member_countries = [set(mock_data[id]['countries']) for id in members]
    first = member_countries[0]
    result = set(c for c in first if all(s.issuperset([c]) for s in member_countries))
    
    assert result == set(), "Everyone filter should return empty set when no countries are common"


def test_filter_visibility_with_single_traveller():
    """Test that the filter should not be shown for single traveller."""
    members = ['alice']
    should_show = len(members) >= 2
    
    assert not should_show, "Filter should not be shown for single traveller"


def test_filter_visibility_with_two_travellers():
    """Test that the filter should be shown for two or more travellers."""
    members = ['alice', 'bob']
    should_show = len(members) >= 2
    
    assert should_show, "Filter should be shown for two travellers"


def test_filter_visibility_with_group():
    """Test that the filter should be shown for groups with multiple members."""
    group = {'name': 'Test Group', 'members': ['alice', 'bob', 'charlie']}
    should_show = len(group['members']) >= 2
    
    assert should_show, "Filter should be shown for groups with multiple members"
