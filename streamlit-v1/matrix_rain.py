#!/usr/bin/env python3
"""
Digital Rain Effect - Matrix Style
Implementación standalone con pygame para visualizar el efecto
"""

import pygame
import random

# --- Configuration ---
WIDTH, HEIGHT = 1200, 800  # Window size
FONT_SIZE = 20
SPEED = 40  # Lower is faster (milliseconds per frame)

# Colors
BLACK = (0, 0, 0)
# Cyan/Blue color to match your image reference
NEON_BLUE = (0, 240, 255) 
# A slightly darker trail color
DARK_TRAIL = (0, 20, 30)

# --- Initialization ---
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Digital Rain - Pro Scanner Login Effect")
font = pygame.font.SysFont('consolas', FONT_SIZE, bold=True)

# Generate characters (Katakana is standard, but we use ASCII for compatibility)
chars = [chr(i) for i in range(48, 126)]  # Numbers, letters, symbols

# Calculate number of columns
columns = WIDTH // FONT_SIZE

# Drops: drops[i] represents the y-position of the text in column i
drops = [1 for _ in range(columns)]

clock = pygame.time.Clock()

def draw():
    """Draw the matrix rain effect"""
    # Instead of clearing the screen completely, we draw a semi-transparent 
    # black rectangle to create the "trail" effect.
    # Note: Pygame doesn't support alpha on the main surface directly in this way easily,
    # so we use a surface wrapper for the fade effect.
    fade_surface = pygame.Surface((WIDTH, HEIGHT))
    fade_surface.set_alpha(20)  # Controls the length of the trail (lower = longer trail)
    fade_surface.fill(BLACK)
    screen.blit(fade_surface, (0, 0))

    for i in range(0, len(drops)):
        # Select a random character
        char = random.choice(chars)
        char_render = font.render(char, True, NEON_BLUE)
        
        # Draw the character
        x = i * FONT_SIZE
        y = drops[i] * FONT_SIZE
        screen.blit(char_render, (x, y))

        # Reset drop to top randomly or move it down
        if drops[i] * FONT_SIZE > HEIGHT and random.random() > 0.975:
            drops[i] = 0
        
        drops[i] += 1

# --- Main Loop ---
print("🌧️  Digital Rain Effect Running...")
print("💡 Press ESC or close window to exit")
print("🎨 Color: Cyan/Blue (#00F0FF)")

running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

    draw()
    pygame.display.flip()
    clock.tick(30)  # Limit to 30 FPS

pygame.quit()
print("✅ Digital Rain effect closed")
