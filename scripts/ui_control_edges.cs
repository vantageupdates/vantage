// Code-native skin primitives, adapted from the existing SoftGoldRenderer.
// Generates dedicated control edges and Actions button cells; never item art.
using System;
using System.IO;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;

public static class VantageControlEdgesRenderer {
    // Native attack drawing owns visibility/red tint. Outline the full client
    // area, not the name row; retain a transparent interior and a subpixel rim.
    public static void RenderAttack(string destination) {
        if(Path.GetFileName(destination)!="AttackIndicator.tga")
            throw new ArgumentException("Only the attack indicator atlas is supported.");
        using(var atlas=new Bitmap(512,128,PixelFormat.Format32bppArgb)) {
            using(var g=Graphics.FromImage(atlas))
            using(var path=Round(0.7f,0.7f,259.6f,54.6f,5.5f))
            using(var pen=new Pen(Color.FromArgb(210,255,255,255),0.75f)) {
                g.SmoothingMode=SmoothingMode.AntiAlias;
                g.DrawPath(pen,path);
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                byte[] header=new byte[18]; header[2]=2;
                header[13]=2; header[14]=128; header[16]=32; header[17]=40;
                output.Write(header);
                for(int y=0;y<128;y++) for(int x=0;x<512;x++) {
                    Color c=atlas.GetPixel(x,y);
                    output.Write(c.B); output.Write(c.G); output.Write(c.R); output.Write(c.A);
                }
            }
        }
    }
    static GraphicsPath Round(float x,float y,float w,float h,float r) {
        var p=new GraphicsPath(); float d=2*r;
        p.AddArc(x,y,d,d,180,90); p.AddArc(x+w-d,y,d,d,270,90);
        p.AddArc(x+w-d,y+h-d,d,d,0,90); p.AddArc(x,y+h-d,d,d,90,90);
        p.CloseFigure(); return p;
    }
    // Exact pixel coverage, without bicubic ringing or a baked square backdrop.
    // Negative distance is inside the rounded rectangle. Coordinates are local.
    static double RoundedDistance(double x,double y,int w,int h,double radius,double inset) {
        double qx=Math.Abs(x-w/2.0)-(w/2.0-inset-radius);
        double qy=Math.Abs(y-h/2.0)-(h/2.0-inset-radius);
        return Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2))
            +Math.Min(Math.Max(qx,qy),0)-radius;
    }
    static int RoundedAlpha(int x,int y,int w,int h,double radius,double inset) {
        int inside=0;
        for(int sy=0;sy<8;sy++) for(int sx=0;sx<8;sx++)
            if(RoundedDistance(x+(sx+0.5)/8,y+(sy+0.5)/8,w,h,radius,inset)<=0) inside++;
        return (255*inside+32)/64;
    }
    static Color ActionsPixel(int x,int y,int state,int width=128) {
        int alpha=RoundedAlpha(x,y,width,18,7,0.5);
        if(alpha==0) return Color.Transparent;
        double t=(y+0.5)/18;
        bool down=state==2 || state==3;
        double tone=down ? 17+9*t : 30-13*t+9*Math.Exp(-Math.Pow((t-0.22)/0.20,2));
        if(state==1 || state==3) tone+=7;
        if(state==4) tone=16+4*(1-t);
        double depth=Math.Max(0,-RoundedDistance(x+0.5,y+0.5,width,18,7,0.5));
        double rim=0.18*Math.Exp(-Math.Pow(depth/0.65,2));
        // Only the fine structural rim is gold; the softly raised face is neutral.
        return Color.FromArgb(alpha,(int)Math.Round(tone*(1-rim)+158*rim),
            (int)Math.Round(tone*(1-rim)+131*rim),(int)Math.Round(tone*(1-rim)+75*rim));
    }
    public static void RepairSpellCorners(string destination) {
        if(Path.GetFileName(destination)!="v3_controls.tga")
            throw new ArgumentException("Only the spell control atlas is supported.");
        byte[] data=File.ReadAllBytes(destination);
        if(data.Length<18+256*256*4 || data[0]!=0 || data[1]!=0 || data[2]!=2
            || data[12]!=0 || data[13]!=1 || data[14]!=0 || data[15]!=1
            || data[16]!=32 || data[17]!=40)
            throw new ArgumentException("Expected the reviewed top-origin 256x256 BGRA atlas.");
        // Clip every native layer, including all four Spells header states.
        // Min (not multiplication) makes repeated repairs byte-idempotent.
        int[,] cells={{0,28},{28,28},{56,28},{84,14},{98,14},{112,14},{126,14}};
        for(int n=0;n<cells.GetLength(0);n++) {
            int top=cells[n,0], height=cells[n,1];
            double radius=height==28 ? 6 : 5;
            for(int y=0;y<height;y++) for(int x=0;x<120;x++) {
                int i=18+((top+y)*256+x)*4;
                int coverage=RoundedAlpha(x,y,120,height,radius,0.25);
                data[i+3]=(byte)Math.Min(data[i+3],coverage);
                if(data[i+3]==0) data[i]=data[i+1]=data[i+2]=0;
            }
        }
        File.WriteAllBytes(destination,data);
    }
    public static void RepairSlotCorners(string destination) {
        string name=Path.GetFileName(destination);
        if(name!="VantageSlotHints.tga" && name!="classic_pieces01.tga")
            throw new ArgumentException("Only the two native slot background atlases are supported.");
        byte[] data=File.ReadAllBytes(destination);
        if(data.Length<18+256*256*4 || data[0]!=0 || data[1]!=0 || data[2]!=2
            || data[12]!=0 || data[13]!=1 || data[14]!=0 || data[15]!=1
            || data[16]!=32 || data[17]!=40)
            throw new ArgumentException("Expected the reviewed top-origin 256x256 BGRA atlas.");
        int count=name=="VantageSlotHints.tga" ? 18 : 1;
        for(int cell=0;cell<count;cell++) {
            int left=count==18 ? 2+(cell%6)*42 : 0;
            int top=count==18 ? 2+(cell/6)*42 : 117;
            for(int y=0;y<40;y++) for(int x=0;x<40;x++) {
                int i=18+((top+y)*256+left+x)*4;
                data[i+3]=(byte)Math.Min(data[i+3],RoundedAlpha(x,y,40,40,6,0.25));
                if(data[i+3]==0) data[i]=data[i+1]=data[i+2]=0;
            }
        }
        File.WriteAllBytes(destination,data);
    }
    public static void RepairTitleButtonCorners(string destination) {
        if(Path.GetFileName(destination)!="quickbar_frames.tga")
            throw new ArgumentException("Only the reviewed title-control atlas is supported.");
        byte[] data=File.ReadAllBytes(destination);
        if(data.Length!=18+512*512*4 || data[0]!=0 || data[1]!=0 || data[2]!=2
            || data[12]!=0 || data[13]!=2 || data[14]!=0 || data[15]!=2
            || data[16]!=32 || data[17]!=40)
            throw new ArgumentException("Expected the reviewed top-origin 512x512 BGRA atlas.");
        // Both native Close and Minimize, in every interactive state. Do not
        // touch title strips, frame art, glyph centers or any other controls.
        for(int kind=0;kind<2;kind++) for(int state=0;state<5;state++) {
            int left=(kind==0?148:364)+state*14, top=kind==0?2:42;
            for(int y=0;y<12;y++) for(int x=0;x<12;x++) {
                int i=18+((top+y)*512+left+x)*4;
                data[i+3]=(byte)Math.Min(data[i+3],RoundedAlpha(x,y,12,12,5.5,0.5));
                if(data[i+3]==0) data[i]=data[i+1]=data[i+2]=0;
            }
        }
        File.WriteAllBytes(destination,data);
    }
    public static void Render(string destination) {
        if(Path.GetFileName(destination)!="VantageControlEdges.tga")
            throw new ArgumentException("Only the dedicated edge atlas is supported.");
        using(var atlas=new Bitmap(512,128,PixelFormat.Format32bppArgb))
        using(var frame=new Bitmap(40,40,PixelFormat.Format32bppArgb)) {
            for(int y=0;y<40;y++) for(int x=0;x<40;x++) {
                int coverage=RoundedAlpha(x,y,40,40,6,0.5)-RoundedAlpha(x,y,40,40,5.4,1.1);
                int alpha=(Math.Max(0,coverage)*120+127)/255;
                frame.SetPixel(x,y,alpha==0 ? Color.Transparent : Color.FromArgb(alpha,108,91,61));
            }
            // x, y, width, height, source x, source y. Keep every XML slice exact.
            // Wider corner spans leave the diagonal clear without changing the
            // one-pixel client inset or the native inventory icon rectangles.
            int[,] slices={ {2,2,6,1,0,0},{10,2,1,1,20,0},{13,2,6,1,34,0},
                {21,2,1,5,39,1},{24,2,1,1,39,20},{27,2,1,5,39,34},
                {30,2,6,1,34,39},{38,2,1,1,20,39},{41,2,6,1,0,39},
                {49,2,1,5,0,1},{52,2,1,1,0,20},{55,2,1,5,0,34} };
            for(int n=0;n<slices.GetLength(0);n++)
                for(int y=0;y<slices[n,3];y++) for(int x=0;x<slices[n,2];x++)
                    atlas.SetPixel(slices[n,0]+x,slices[n,1]+y,
                        frame.GetPixel(slices[n,4]+x,slices[n,5]+y));
            {
                int[,] strips={{2,240},{246,100}};
                // Neutral transparent relief, clipped by a live HP gauge.
                // No static marks remain visible when a party slot is empty.
                for(int n=0;n<2;n++) {
                    int start=strips[n,0], width=strips[n,1];
                    for(int y=3;y<18;y++) for(int x=1;x<width-1;x++) {
                        float edge=Math.Min(x,width-1-x);
                        float curve=Math.Max(0,7-edge);
                        float dy=y-10;
                        if(curve*curve+dy*dy>49 && edge<7) continue;
                        int alpha=y<=9 ? (int)Math.Round(50.0*(10-y)/7) : (int)Math.Round(38.0*(y-10)/7);
                        int rgb=y<=9 ? 255 : 0;
                        bool divider=false;
                        for(int i=1;i<5;i++) if(x==i*width/5-1) divider=true;
                        // Slight visibility lift only: 14% white, still translucent.
                        if(divider) { alpha=36; rgb=255; }
                        atlas.SetPixel(start+x,12+y,Color.FromArgb(alpha,rgb,rgb,rgb));
                    }
                }
            }
            // Spell-only neutral outline. A static screen piece draws this
            // after the native school-tinted gem; never tint the grey border.
            // Dedicated 120x28 cell, clear of HP strips and shared gold slices.
            using(var high=new Bitmap(480,112,PixelFormat.Format32bppArgb))
            using(var edge=new Bitmap(120,28,PixelFormat.Format32bppArgb)) {
                using(var g=Graphics.FromImage(high))
                using(var path=Round(3,3,474,106,22))
                using(var pen=new Pen(Color.FromArgb(155,148,148,148),4)) {
                    g.SmoothingMode=SmoothingMode.AntiAlias;
                    g.DrawPath(pen,path);
                }
                using(var g=Graphics.FromImage(edge)) {
                    g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    g.DrawImage(high,new Rectangle(0,0,120,28),0,0,480,112,GraphicsUnit.Pixel);
                }
                for(int y=0;y<28;y++) for(int x=0;x<120;x++)
                    atlas.SetPixel(2+x,34+y,edge.GetPixel(x,y));
            }
            // Actions-only art matches the 128x18 hitboxes exactly. The shared
            // 120x24 A_Btn* sprites stay unchanged for every other window.
            // Rebuild the five faces at final size instead of squeezing old
            // 24px artwork. Equal-radius corners and six clear atlas rows.
            for(int state=0;state<5;state++)
                for(int y=0;y<18;y++) for(int x=0;x<128;x++)
                    atlas.SetPixel(352+x,4+state*24+y,ActionsPixel(x,y,state));
            // Pet's half-width commands get native 62x18 art, not a squashed
            // wide button. These isolated cells never overlap existing art.
            int[,] petCells={{128,34},{256,34},{256,54},{256,74},{256,94}};
            for(int state=0;state<5;state++)
                for(int y=0;y<18;y++) for(int x=0;x<62;x++)
                    atlas.SetPixel(petCells[state,0]+x,petCells[state,1]+y,
                        ActionsPixel(x,y,state,62));
            // Compact identity tab. Neutral fill, softly rounded gold rim;
            // version text is a native XML label, never baked into the image.
            using(var high=new Bitmap(808,80,PixelFormat.Format32bppArgb))
            using(var tab=new Bitmap(202,20,PixelFormat.Format32bppArgb)) {
                using(var g=Graphics.FromImage(high))
                using(var path=Round(1.6f,1.6f,804.8f,76.8f,18))
                using(var fill=new LinearGradientBrush(new Rectangle(0,0,808,80),
                    Color.FromArgb(24,25,27),Color.FromArgb(11,12,14),90f))
                using(var rim=new Pen(Color.FromArgb(115,158,131,75),2.4f)) {
                    g.SmoothingMode=SmoothingMode.AntiAlias;
                    g.FillPath(fill,path);
                    g.DrawPath(rim,path);
                }
                using(var g=Graphics.FromImage(tab)) {
                    g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    g.DrawImage(high,new Rectangle(0,0,202,20),
                        0,0,808,80,GraphicsUnit.Pixel);
                }
                for(int y=0;y<20;y++) for(int x=0;x<202;x++)
                    atlas.SetPixel(2+x,70+y,tab.GetPixel(x,y));
            }
            // A slim spell-window footer; never change any gem or existing bar.
            using(var high=new Bitmap(480,60,PixelFormat.Format32bppArgb))
            using(var footer=new Bitmap(120,15,PixelFormat.Format32bppArgb)) {
                using(var g=Graphics.FromImage(high))
                using(var path=Round(1.6f,1.6f,476.8f,56.8f,16))
                using(var fill=new LinearGradientBrush(new Rectangle(0,0,480,60),
                    Color.FromArgb(24,25,27),Color.FromArgb(11,12,14),90f))
                using(var rim=new Pen(Color.FromArgb(90,158,131,75),2f)) {
                    g.SmoothingMode=SmoothingMode.AntiAlias;
                    g.FillPath(fill,path);
                    g.DrawPath(rim,path);
                }
                using(var g=Graphics.FromImage(footer)) {
                    g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    g.DrawImage(high,new Rectangle(0,0,120,15),
                        0,0,480,60,GraphicsUnit.Pixel);
                }
                for(int y=0;y<15;y++) for(int x=0;x<120;x++)
                    atlas.SetPixel(2+x,96+y,footer.GetPixel(x,y));
            }
            string barSource=Path.Combine(Path.GetDirectoryName(destination),"dzbars.png");
            using(var source=new Bitmap(barSource))
            using(var cell=source.Clone(new Rectangle(0,200,240,11),PixelFormat.Format32bppArgb))
            using(var fill=new Bitmap(116,9,PixelFormat.Format32bppArgb))
            using(var attributes=new ImageAttributes()) {
                attributes.SetWrapMode(WrapMode.TileFlipXY);
                using(var g=Graphics.FromImage(fill)) {
                    g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                    g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                    g.DrawImage(cell,new Rectangle(0,0,116,9),0,0,240,11,
                        GraphicsUnit.Pixel,attributes);
                }
                // Fourfold sampled pill mask removes the original atlas
                // backdrop from the ends while preserving its soft relief.
                for(int y=0;y<9;y++) for(int x=0;x<116;x++) {
                    int covered=0;
                    for(int sy=0;sy<4;sy++) for(int sx=0;sx<4;sx++) {
                        float px=x+(sx+0.5f)/4, py=y+(sy+0.5f)/4;
                        float dx=px<4.5f ? px-4.5f : px>111.5f ? px-111.5f : 0;
                        float dy=py-4.5f;
                        if(dx*dx+dy*dy<=20.25f) covered++;
                    }
                    Color c=fill.GetPixel(x,y);
                    int alpha=(c.A*covered+8)/16;
                    atlas.SetPixel(128+x,96+y,alpha==0 ? Color.Transparent :
                        Color.FromArgb(alpha,c.R,c.G,c.B));
                }
            }
            using(var output=new BinaryWriter(File.Create(destination))) {
                byte[] header=new byte[18]; header[2]=2; header[13]=2;
                header[14]=128; header[16]=32; header[17]=40; output.Write(header);
                for(int y=0;y<128;y++) for(int x=0;x<512;x++) {
                    Color c=atlas.GetPixel(x,y);
                    output.Write(c.B); output.Write(c.G); output.Write(c.R); output.Write(c.A);
                }
            }
        }
    }
}
