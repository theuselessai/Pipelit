Feature: Loop and Filter
  Process a collection of items, extract information, and filter results

  Background:
    Given the workflow is triggered manually
    And the user has at least one LLM credential configured

  Scenario: Generate test items
    When the workflow starts
    Then generate_items produces a list of items
    And each item has properties to extract

  Scenario: Loop processes each item
    Given generate_items produced 4 items
    When the loop executes
    Then extract_info runs once per item
    And results are collected for each iteration

  Scenario: Extract structured data
    Given an item with unstructured data
    When extract_info processes the item
    Then it extracts structured fields
    And validates the extracted data

  Scenario: Filter results
    Given the loop produced 4 results
    When filter_results executes
    Then only items matching criteria are kept
    And the filtered list is returned
