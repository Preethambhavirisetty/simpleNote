#!/bin/bash

# SimpleNote Log Viewer Script

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   SimpleNote Log Viewer               ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

show_menu() {
    echo -e "${GREEN}Select logs to view:${NC}"
    echo "  1) All services (live tail)"
    echo "  2) Backend only (live tail)"
    echo "  3) Frontend only (live tail)"
    echo "  4) Backend app log (file)"
    echo "  5) Nginx access log"
    echo "  6) Nginx error log"
    echo "  7) Nginx API log"
    echo "  8) Last 100 lines - Backend"
    echo "  9) Last 100 lines - Frontend"
    echo "  0) Exit"
    echo ""
    read -p "Enter choice [0-9]: " choice
}

while true; do
    show_menu
    
    case $choice in
        1)
            echo -e "${YELLOW}Showing all logs (Ctrl+C to exit)...${NC}"
            docker compose logs -f
            ;;
        2)
            echo -e "${YELLOW}Showing backend logs (Ctrl+C to exit)...${NC}"
            docker compose logs -f simplenote-backend
            ;;
        3)
            echo -e "${YELLOW}Showing frontend logs (Ctrl+C to exit)...${NC}"
            docker compose logs -f simplenote-frontend
            ;;
        4)
            echo -e "${YELLOW}Showing backend app log (Ctrl+C to exit)...${NC}"
            docker compose exec simplenote-backend tail -f /app/logs/app.log 2>/dev/null || \
                echo "Container not running or log file not found"
            ;;
        5)
            echo -e "${YELLOW}Showing nginx access log (last 50 lines)...${NC}"
            docker compose exec simplenote-frontend tail -50 /var/log/nginx/access.log 2>/dev/null || \
                echo "Container not running or log file not found"
            echo ""
            read -p "Press Enter to continue..."
            ;;
        6)
            echo -e "${YELLOW}Showing nginx error log (last 50 lines)...${NC}"
            docker compose exec simplenote-frontend tail -50 /var/log/nginx/error.log 2>/dev/null || \
                echo "Container not running or log file not found"
            echo ""
            read -p "Press Enter to continue..."
            ;;
        7)
            echo -e "${YELLOW}Showing nginx API log (last 50 lines)...${NC}"
            docker compose exec simplenote-frontend tail -50 /var/log/nginx/api_access.log 2>/dev/null || \
                echo "Container not running or log file not found"
            echo ""
            read -p "Press Enter to continue..."
            ;;
        8)
            echo -e "${YELLOW}Last 100 lines - Backend:${NC}"
            docker compose logs --tail=100 simplenote-backend
            echo ""
            read -p "Press Enter to continue..."
            ;;
        9)
            echo -e "${YELLOW}Last 100 lines - Frontend:${NC}"
            docker compose logs --tail=100 simplenote-frontend
            echo ""
            read -p "Press Enter to continue..."
            ;;
        0)
            echo "Exiting..."
            exit 0
            ;;
        *)
            echo -e "${YELLOW}Invalid choice. Please try again.${NC}"
            sleep 2
            ;;
    esac
    
    echo ""
done

