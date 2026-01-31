"""
Knowledge graph module for domain knowledge representation.

This module provides graph-based domain knowledge that agents can query
to make informed decisions about slot-filling, search, and recommendations.

Example usage:
    >>> from app.knowledge import get_knowledge_graph, GraphQueryEngine
    >>>
    >>> # Load a graph
    >>> graph = get_knowledge_graph('skincare')
    >>>
    >>> # Find a problem
    >>> problem = graph.find_problem_by_synonym('dark spots')
    >>> print(problem)  # 'dark_spots'
    >>>
    >>> # Get interview questions
    >>> questions = GraphQueryEngine.get_interview_questions('skincare', 'dark_spots')
    >>> print(questions[0]['question']['text'])  # "What is your skin type?"
"""

from .graph_loader import (
    KnowledgeGraph,
    get_knowledge_graph,
    reload_graph,
    list_available_graphs,
)

from .query_engine import GraphQueryEngine

__all__ = [
    'KnowledgeGraph',
    'get_knowledge_graph',
    'reload_graph',
    'list_available_graphs',
    'GraphQueryEngine',
]
